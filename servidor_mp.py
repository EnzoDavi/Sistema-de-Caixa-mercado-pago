"""
Servidor da trava Pix - QR Code FIXO (QR estático de caixa do Mercado Pago).

Como funciona:
  - O caixa (criado uma vez com configurar_caixa.py) tem um QR que nunca muda.
  - O servidor deixa sempre uma "order" de R$ VALOR_LIBERACAO carregada nesse caixa.
  - Quem escaneia o QR paga essa order. O Mercado Pago avisa pelo webhook,
    o servidor libera a trava e JÁ carrega uma order nova no caixa.
  - Se uma order expirar sem ser paga, o servidor carrega outra sozinho.

Rotas:
  POST /webhook/mp              -> notificações do Mercado Pago (evento "Order")
  GET  /trava/<id>/pendente     -> a ESP32 pergunta se deve abrir

Instale:  pip install flask requests
Variáveis de ambiente:
  MP_ACCESS_TOKEN     -> Access Token de produção (APP_USR-...)
  MP_WEBHOOK_SECRET   -> assinatura secreta (Webhooks no painel)
  TRAVA_TOKEN         -> senha que a ESP32 usa
"""
import hashlib
import hmac
import json
import os
import threading
import time
import uuid

import requests
from flask import Flask, jsonify, request

ACCESS_TOKEN = os.environ["MP_ACCESS_TOKEN"]
WEBHOOK_SECRET = os.environ["MP_WEBHOOK_SECRET"]
TRAVA_TOKEN = os.environ["TRAVA_TOKEN"]

VALOR_LIBERACAO = "1.00"        # valor de cada liberação (texto com 2 casas)
POS_EXTERNAL_ID = "TRAVA01POS"  # igual ao configurar_caixa.py
TRAVA_ID = "trava-01"           # igual ao TRAVA_ID da ESP32
VALIDADE_ORDEM = "PT720H"       # cada order dura 30 dias; o servidor renova sozinho
ARQ_ESTADO = "estado.json"      # guarda a order atual e os pagamentos já usados

API = "https://api.mercadopago.com"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

app = Flask(__name__)
lock = threading.Lock()
liberacoes = {}                 # trava_id -> quantas aberturas pendentes


# ---------------------------------------------------------------- estado salvo em disco
def carregar_estado():
    try:
        with open(ARQ_ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ordem_atual": None, "usados": []}


estado = carregar_estado()
usados = set(estado.get("usados", []))


def salvar_estado():
    estado["usados"] = sorted(usados)
    with open(ARQ_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2)


# ---------------------------------------------------------------- orders no caixa
def consultar_ordem(ordem_id):
    r = requests.get(f"{API}/v1/orders/{ordem_id}", headers=HEADERS, timeout=15)
    if r.status_code != 200:
        print(f"[order] erro ao consultar {ordem_id}: {r.status_code} {r.text}")
        return None
    return r.json()


def criar_ordem():
    corpo = {
        "type": "qr",
        "total_amount": VALOR_LIBERACAO,
        "description": f"Liberacao {TRAVA_ID}",
        "external_reference": f"{TRAVA_ID}-{uuid.uuid4().hex[:12]}",
        "expiration_time": VALIDADE_ORDEM,
        "config": {"qr": {"external_pos_id": POS_EXTERNAL_ID, "mode": "static"}},
        "transactions": {"payments": [{"amount": VALOR_LIBERACAO}]},
    }
    r = requests.post(
        f"{API}/v1/orders",
        json=corpo,
        headers={**HEADERS, "X-Idempotency-Key": str(uuid.uuid4())},
        timeout=15,
    )
    if r.status_code >= 300:
        print(f"[order] ERRO ao criar order: {r.status_code} {r.text}")
        return None
    ordem = r.json()
    print(f"[order] nova order carregada no caixa: {ordem['id']} (R$ {VALOR_LIBERACAO})")
    return ordem["id"]


def garantir_ordem_ativa():
    """Se o caixa não tiver uma order aguardando pagamento, cria uma."""
    with lock:
        atual = estado.get("ordem_atual")
        if atual:
            ordem = consultar_ordem(atual)
            if ordem and ordem.get("status") in ("created", "action_required"):
                return                              # ainda está valendo
        novo = criar_ordem()
        if novo:
            estado["ordem_atual"] = novo
            salvar_estado()


def vigia_do_caixa():
    """Roda em segundo plano: a cada minuto confere se há order ativa."""
    while True:
        try:
            garantir_ordem_ativa()
        except Exception as e:                      # não deixa a thread morrer
            print("[vigia] erro:", e)
        time.sleep(60)


# ---------------------------------------------------------------- webhook
def assinatura_valida(data_id: str) -> bool:
    """Valida o header x-signature (ts=...,v1=...) enviado pelo Mercado Pago."""
    x_sig = request.headers.get("x-signature", "")
    x_req = request.headers.get("x-request-id", "")
    partes = dict(p.strip().split("=", 1) for p in x_sig.split(",") if "=" in p)
    ts, v1 = partes.get("ts"), partes.get("v1")
    if not ts or not v1:
        return False
    manifesto = f"id:{data_id.lower()};request-id:{x_req};ts:{ts};"
    esperado = hmac.new(WEBHOOK_SECRET.encode(), manifesto.encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, v1)


def liberar_trava(trava_id: str):
    with lock:
        liberacoes[trava_id] = liberacoes.get(trava_id, 0) + 1
    print(f">>> LIBERAR {trava_id} (aguardando a ESP32 buscar)")


@app.post("/webhook/mp")
def webhook():
    tipo = request.args.get("type") or request.args.get("topic")
    data_id = request.args.get("data.id") or request.args.get("id") or ""
    print(f"[webhook] chegou: type={tipo} id={data_id}")
    if tipo != "order" or not data_id:
        print("[webhook] ignorado (não é order)")
        return "", 200

    if not assinatura_valida(data_id):
        print("[webhook] ASSINATURA INVÁLIDA -> confira MP_WEBHOOK_SECRET")
        return "", 401

    ordem = consultar_ordem(data_id)
    if not ordem:
        return "", 200

    status = ordem.get("status")
    pos = ordem.get("config", {}).get("qr", {}).get("external_pos_id")
    valor = float(ordem.get("total_amount") or 0)
    print(f"[webhook] order={ordem['id']} status={status} valor={valor} caixa={pos}")

    if (status == "processed"
            and pos == POS_EXTERNAL_ID
            and valor >= float(VALOR_LIBERACAO)
            and ordem["id"] not in usados):
        with lock:
            usados.add(ordem["id"])
            salvar_estado()
        liberar_trava(TRAVA_ID)

    # pagou, expirou ou foi cancelada -> carrega a próxima order no caixa
    if status in ("processed", "expired", "canceled", "refunded"):
        threading.Thread(target=garantir_ordem_ativa, daemon=True).start()

    return "", 200


# ---------------------------------------------------------------- ESP32
@app.get("/trava/<trava_id>/pendente")
def trava_pendente(trava_id):
    """Responde {"abrir": true} uma única vez para cada pagamento aprovado."""
    if request.headers.get("X-Trava-Token") != TRAVA_TOKEN:
        return jsonify(erro="token invalido"), 403
    with lock:
        n = liberacoes.get(trava_id, 0)
        if n > 0:
            liberacoes[trava_id] = n - 1
            print(f"[esp32] {trava_id} buscou a liberação -> ABRINDO")
            return jsonify(abrir=True)
    return jsonify(abrir=False)


if __name__ == "__main__":
    threading.Thread(target=vigia_do_caixa, daemon=True).start()
    app.run(port=5000)
