/*
  Placa: ESP32 Dev Module (Arduino IDE)
  Biblioteca: "LiquidCrystal I2C" (Frank de Brabander) - instale pelo Gerenciador de Bibliotecas

  Ligações:
    LED vermelho: GPIO 25 -> resistor 220 ohm -> perna longa do LED; perna curta -> GND
    LED verde:    GPIO 26 -> resistor 220 ohm -> perna longa do LED; perna curta -> GND
    LCD I2C:      VCC -> VIN (5V) | GND -> GND | SDA -> GPIO 21 | SCL -> GPIO 22
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ------------------- CONFIGURE AQUI -------------------
const char* WIFI_SSID   = "Nome_rede";
const char* WIFI_SENHA  = "Senha_rede";

const char* SERVIDOR    = "Link_servidor";
const char* TRAVA_ID    = "trava-01";
const char* TRAVA_TOKEN = "senha";          

const int PINO_LED_VERMELHO = 25;
const int PINO_LED_VERDE    = 26;
const uint8_t ENDERECO_LCD  = 0x27;   // se a tela ficar em branco, tente 0x3F

const int TEMPO_PAGO_MS = 5000;       // quanto tempo mostra "pagamento recebido"
const int INTERVALO_MS  = 1000;       // de quanto em quanto tempo pergunta ao servidor
// ------------------------------------------------------

LiquidCrystal_I2C lcd(ENDERECO_LCD, 16, 2);

void mostrar(const char* linha1, const char* linha2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(linha1);
  lcd.setCursor(0, 1);
  lcd.print(linha2);
}

void estadoAguardando() {
  digitalWrite(PINO_LED_VERMELHO, HIGH);
  digitalWrite(PINO_LED_VERDE, LOW);
  mostrar("Aguardando", "pagamento...");
}

void estadoPago() {
  Serial.println(">>> PAGAMENTO RECEBIDO");
  digitalWrite(PINO_LED_VERMELHO, LOW);
  digitalWrite(PINO_LED_VERDE, HIGH);
  mostrar("Pagamento", "recebido!");
  delay(TEMPO_PAGO_MS);
  estadoAguardando();
}

void conectarWiFi() {
  mostrar("Conectando", "ao WiFi...");
  Serial.print("Conectando ao WiFi");
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.print("\nConectado! IP: ");
  Serial.println(WiFi.localIP());
  estadoAguardando();
}

void verificarServidor() {
  WiFiClientSecure cliente;
  cliente.setInsecure();   // aceita o certificado sem validar (ok para testes)

  HTTPClient http;
  String url = String(SERVIDOR) + "/trava/" + TRAVA_ID + "/pendente";
  http.begin(cliente, url);
  http.addHeader("X-Trava-Token", TRAVA_TOKEN);
  http.addHeader("ngrok-skip-browser-warning", "1");
  http.setTimeout(8000);

  int codigo = http.GET();
  if (codigo == 200) {
    String resposta = http.getString();
    if (resposta.indexOf("true") >= 0) {
      estadoPago();
    }
  } else if (codigo == 403) {
    Serial.println("Token recusado: confira TRAVA_TOKEN");
    mostrar("Erro:", "token invalido");
  } else {
    Serial.printf("Falha ao consultar servidor (codigo %d)\n", codigo);
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_LED_VERMELHO, OUTPUT);
  pinMode(PINO_LED_VERDE, OUTPUT);

  Wire.begin(21, 22);      // SDA, SCL
  lcd.init();
  lcd.backlight();

  conectarWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    conectarWiFi();
  }
  verificarServidor();
  delay(INTERVALO_MS);
}
