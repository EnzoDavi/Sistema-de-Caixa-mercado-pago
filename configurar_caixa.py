"""
RODE UMA ÚNICA VEZ.
Cria no Mercado Pago uma "loja" e um "caixa" e baixa o QR Code FIXO do caixa.
Esse QR não expira: é ele que você imprime / cola na trava.

Uso (no terminal com a .venv ativa):
    $env:MP_ACCESS_TOKEN="APP_USR-..."
    python configurar_caixa.py

Gera:
    qr_caixa.png   -> imagem do QR fixo (imprima esta)
    qr_caixa.txt   -> o mesmo QR em texto (Pix copia e cola)
    caixa.json     -> resposta completa do Mercado Pago (guarde)
"""
import json
import os
import sys
import uuid

import requests

ACCESS_TOKEN = os.environ["MP_ACCESS_TOKEN"]
API = "https://api.mercadopago.com"
H = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

# Têm que ser iguais aos do servidor_mp.py (só letras e números)
LOJA_EXTERNAL_ID = "TRAVA01LOJA"
POS_EXTERNAL_ID = "TRAVA01POS"

# Endereço onde a trava fica (use dados reais)
LOCAL = {
    "street_number": "0",
    "street_name": "Campus Universitario Darcy Ribeiro",
    "city_name": "Brasília",
    "state_name": "Distrito Federal",
    "latitude": -15.7633,
    "longitude": -47.8706,
    "reference": "Trava Pix",
}


def falhar(etapa, r):
    print(f"\nERRO ao {etapa}: {r.status_code}")
    print(r.text)
    sys.exit(1)


# 1) Descobre o id do usuário dono do token
r = requests.get(f"{API}/users/me", headers=H, timeout=15)
if r.status_code != 200:
    falhar("consultar usuário", r)
user_id = r.json()["id"]
print("Usuário:", user_id)

# 2) Cria a loja
r = requests.post(
    f"{API}/users/{user_id}/stores",
    headers=H,
    json={"name": "Trava Pix", "external_id": LOJA_EXTERNAL_ID, "location": LOCAL},
    timeout=15,
)
if r.status_code >= 300:
    falhar("criar loja", r)
store_id = r.json()["id"]
print("Loja criada:", store_id)

# 3) Cria o caixa (é ele que tem o QR fixo)
r = requests.post(
    f"{API}/v2/pos",
    headers={**H, "X-Idempotency-Key": str(uuid.uuid4())},
    json={
        "name": "Trava 01",
        "store_id": str(store_id),
        "external_id": POS_EXTERNAL_ID,
        "config": {"qr": {"operating_mode": "pdv"}},
    },
    timeout=15,
)
if r.status_code >= 300:
    falhar("criar caixa", r)
caixa = r.json()
print("Caixa criado:", caixa.get("id"))

with open("caixa.json", "w", encoding="utf-8") as f:
    json.dump(caixa, f, indent=2, ensure_ascii=False)

# 4) Salva o QR fixo
qr = caixa.get("qr_response") or {}
if qr.get("qr_code"):
    with open("qr_caixa.txt", "w", encoding="utf-8") as f:
        f.write(qr["qr_code"])
    print("QR em texto salvo em qr_caixa.txt")

if qr.get("image"):
    img = requests.get(qr["image"], timeout=15)
    if img.status_code == 200:
        with open("qr_caixa.png", "wb") as f:
            f.write(img.content)
        print("Imagem do QR salva em qr_caixa.png")
    print("Link da imagem:", qr["image"])

if qr.get("template_document"):
    print("Modelo para imprimir (PDF):", qr["template_document"])

print("\nPronto! Agora rode o servidor_mp.py.")
