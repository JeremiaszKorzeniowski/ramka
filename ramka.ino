#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <AnimatedGIF.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WebServer.h>
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <WiFiClientSecureBearSSL.h>
#include <WiFiManager.h>

// NodeMCU / ESP-12F -> ST7735 + microSD
// Wspolne SPI: SCK=D5, MISO=D6, MOSI=D7.
constexpr uint8_t TFT_CS = D8;
constexpr uint8_t TFT_DC = D1;
constexpr int8_t TFT_RST = -1;  // RESET ekranu jest polaczony z RST ESP8266.
constexpr uint8_t SD_CARD_CS = D4;

constexpr uint8_t ENCODER_CLK = D2;
constexpr uint8_t ENCODER_DT = D0;
constexpr uint8_t ENCODER_SW = D3;

constexpr int16_t SCREEN_WIDTH = 160;
constexpr int16_t SCREEN_HEIGHT = 128;
constexpr uint32_t SHOW_TIME_MS = 12000;
constexpr uint8_t MAX_GIFS = 32;
constexpr uint32_t MAX_DOWNLOAD_BYTES = 6UL * 1024UL * 1024UL;
constexpr char WIFI_AP_NAME[] = "RAMKA-SETUP";
constexpr char WIFI_AP_PASSWORD[] = "ramka123";
constexpr char HOST_NAME[] = "ramka";
constexpr char UPLOAD_TEMP_FILE[] = "/upload.tmp";

Adafruit_ST7735 tft(TFT_CS, TFT_DC, TFT_RST);
AnimatedGIF gif;
File gifFile;
File uploadFile;
ESP8266WebServer server(80);
WiFiManager wifiManager;

// ESP8266 SPI czyta dane blokami 32-bitowymi. Wymuszenie wyrownania do 4 bajtow
// zapobiega Exception (9) w SPIClass::writeBytes_().
alignas(4) uint16_t scanline[SCREEN_WIDTH];
String gifFiles[MAX_GIFS];
uint8_t gifCount = 0;
int16_t gifX = 0;
int16_t gifY = 0;
volatile int8_t encoderStep = 0;
volatile bool encoderButtonPressed = false;
volatile uint32_t lastEncoderUs = 0;
volatile uint32_t lastButtonUs = 0;
bool autoPlay = true;
bool autoPlayChanged = false;
bool networkReady = false;
bool mdnsReady = false;
bool libraryDirty = true;
String uploadTarget;
String uploadError;

void showMessage(const __FlashStringHelper *line1, const String &line2 = "") {
  tft.fillScreen(ST77XX_BLACK);
  tft.setCursor(5, 8);
  tft.setTextColor(ST77XX_WHITE);
  tft.setTextSize(1);
  tft.println(line1);
  if (line2.length()) {
    tft.setCursor(5, 24);
    tft.setTextColor(ST77XX_CYAN);
    tft.println(line2);
  }
}

void IRAM_ATTR onEncoderTurn() {
  const uint32_t now = micros();
  if (now - lastEncoderUs < 2500) return;
  lastEncoderUs = now;
  encoderStep = digitalRead(ENCODER_DT) ? 1 : -1;
}

void IRAM_ATTR onEncoderButton() {
  const uint32_t now = micros();
  if (now - lastButtonUs < 50000) return;
  lastButtonUs = now;
  encoderButtonPressed = true;
}

bool pollControls() {
  if (encoderButtonPressed) {
    noInterrupts();
    encoderButtonPressed = false;
    interrupts();
    autoPlay = !autoPlay;
    autoPlayChanged = true;
    return true;
  }
  return encoderStep != 0;
}

void serviceNetwork() {
  if (!networkReady) return;
  server.handleClient();
  if (mdnsReady) MDNS.update();
}

void *gifOpen(const char *filename, int32_t *size) {
  gifFile = SD.open(filename, FILE_READ);
  if (!gifFile) return nullptr;
  *size = static_cast<int32_t>(gifFile.size());
  return &gifFile;
}

void gifClose(void *handle) {
  File *file = static_cast<File *>(handle);
  if (file) file->close();
}

int32_t gifRead(GIFFILE *fileInfo, uint8_t *buffer, int32_t length) {
  File *file = static_cast<File *>(fileInfo->fHandle);
  if (!file || length <= 0) return 0;
  const int32_t remaining = fileInfo->iSize - fileInfo->iPos;
  if (length > remaining) length = remaining;
  const int32_t bytesRead = static_cast<int32_t>(file->read(buffer, length));
  fileInfo->iPos = static_cast<int32_t>(file->position());
  return bytesRead;
}

int32_t gifSeek(GIFFILE *fileInfo, int32_t position) {
  File *file = static_cast<File *>(fileInfo->fHandle);
  if (!file || !file->seek(position, SeekSet)) return -1;
  fileInfo->iPos = static_cast<int32_t>(file->position());
  return fileInfo->iPos;
}

void gifDraw(GIFDRAW *draw) {
  int16_t x = gifX + draw->iX;
  const int16_t y = gifY + draw->iY + draw->y;
  int16_t width = draw->iWidth;
  if (y < 0 || y >= SCREEN_HEIGHT || x >= SCREEN_WIDTH || x + width <= 0) return;

  uint8_t *pixels = draw->pPixels;
  if (x < 0) {
    pixels -= x;
    width += x;
    x = 0;
  }
  if (x + width > SCREEN_WIDTH) width = SCREEN_WIDTH - x;

  uint16_t *palette = draw->pPalette;
  if (!draw->ucHasTransparency) {
    for (int16_t i = 0; i < width; ++i) scanline[i] = palette[pixels[i]];
    tft.drawRGBBitmap(x, y, scanline, width, 1);
    return;
  }

  const uint8_t transparent = draw->ucTransparent;
  int16_t start = 0;
  while (start < width) {
    while (start < width && pixels[start] == transparent) ++start;
    int16_t end = start;
    while (end < width && pixels[end] != transparent) {
      scanline[end - start] = palette[pixels[end]];
      ++end;
    }
    if (end > start) tft.drawRGBBitmap(x + start, y, scanline, end - start, 1);
    start = end;
  }
}

bool openGif(const char *path) {
  if (!gif.open(path, gifOpen, gifClose, gifRead, gifSeek, gifDraw)) {
    Serial.printf("Blad GIF %s: %d\n", path, gif.getLastError());
    return false;
  }
  const int width = gif.getCanvasWidth();
  const int height = gif.getCanvasHeight();
  if (width > SCREEN_WIDTH || height > SCREEN_HEIGHT) {
    Serial.printf("GIF za duzy %s: %dx%d\n", path, width, height);
    gif.close();
    return false;
  }
  gifX = (SCREEN_WIDTH - width) / 2;
  gifY = (SCREEN_HEIGHT - height) / 2;
  return true;
}

String safeGifPath(String name) {
  name.replace('\\', '/');
  const int slash = name.lastIndexOf('/');
  if (slash >= 0) name = name.substring(slash + 1);
  String clean;
  clean.reserve(48);
  for (uint16_t i = 0; i < name.length() && clean.length() < 44; ++i) {
    const char c = name[i];
    if (isalnum(static_cast<unsigned char>(c)) || c == '.' || c == '-' || c == '_') clean += c;
    else if (c == ' ') clean += '_';
  }
  String lower = clean;
  lower.toLowerCase();
  if (!lower.endsWith(".gif") || clean.length() < 5) return "";
  return "/" + clean;
}

String htmlEscape(String value) {
  value.replace("&", "&amp;");
  value.replace("<", "&lt;");
  value.replace(">", "&gt;");
  value.replace("\"", "&quot;");
  return value;
}

void scanGifFiles() {
  gifCount = 0;
  File root = SD.open("/");
  if (!root) {
    libraryDirty = false;
    return;
  }
  File entry = root.openNextFile();
  while (entry && gifCount < MAX_GIFS) {
    if (!entry.isDirectory() && entry.size() > 0) {
      String path = entry.name();
      if (!path.startsWith("/")) path = "/" + path;
      String lower = path;
      lower.toLowerCase();
      if (lower.endsWith(".gif")) gifFiles[gifCount++] = path;
    }
    entry.close();
    entry = root.openNextFile();
    yield();
  }
  root.close();
  for (uint8_t i = 0; i < gifCount; ++i) {
    for (uint8_t j = i + 1; j < gifCount; ++j) {
      if (gifFiles[j].compareTo(gifFiles[i]) < 0) {
        const String tmp = gifFiles[i];
        gifFiles[i] = gifFiles[j];
        gifFiles[j] = tmp;
      }
    }
  }
  libraryDirty = false;
  Serial.printf("Znaleziono GIF: %u\n", gifCount);
}

void playFor(const char *path, uint32_t durationMs) {
  const uint32_t startedAt = millis();
  tft.fillScreen(ST77XX_BLACK);
  while (millis() - startedAt < durationMs) {
    if (!openGif(path)) {
      showMessage(F("Niepoprawny GIF"), path);
      delay(1200);
      return;
    }
    uint16_t frameCount = 0;
    while (millis() - startedAt < durationMs && gif.playFrame(true, nullptr)) {
      ++frameCount;
      serviceNetwork();
      if (pollControls() || libraryDirty) {
        gif.close();
        return;
      }
      yield();
    }
    gif.close();
    // Jednoklatkowy GIF zostaje w pamieci kontrolera ST7735.
    if (frameCount <= 1) {
      while (millis() - startedAt < durationMs) {
        serviceNetwork();
        if (pollControls() || libraryDirty) return;
        delay(1);
      }
      return;
    }
  }
}

String pageHeader() {
  String page;
  page.reserve(2600);
  page += F("<!doctype html><html lang='pl'><head><meta charset='utf-8'>");
  page += F("<meta name='viewport' content='width=device-width,initial-scale=1'><title>Ramka</title><style>");
  page += F("body{font-family:system-ui;background:#111827;color:#f9fafb;max-width:760px;margin:auto;padding:20px}");
  page += F("section{background:#1f2937;padding:18px;border-radius:14px;margin:14px 0}h1{margin-bottom:4px}");
  page += F("input,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #4b5563;margin:4px 0}");
  page += F("input[type=text],input[type=url]{width:95%;background:#111827;color:white}");
  page += F("button{background:#22c55e;color:#052e16;font-weight:700;cursor:pointer}.del{background:#ef4444;color:white}");
  page += F("li{margin:9px 0}.muted{color:#9ca3af}code{color:#67e8f9}</style></head><body>");
  page += F("<h1>Ramka ESP8266</h1><div class='muted'>");
  page += htmlEscape(WiFi.SSID());
  page += F(" · ");
  page += WiFi.localIP().toString();
  page += F(" · <code>ramka.local</code></div>");
  return page;
}

void handleRoot() {
  String page = pageHeader();
  page += F("<section><h2>Animacje na karcie</h2><ul>");
  if (gifCount == 0) page += F("<li>Brak plikow GIF</li>");
  for (uint8_t i = 0; i < gifCount; ++i) {
    File file = SD.open(gifFiles[i], FILE_READ);
    const uint32_t size = file ? file.size() : 0;
    file.close();
    const String displayName = htmlEscape(gifFiles[i].substring(1));
    page += F("<li><b>");
    page += displayName;
    page += F("</b> <span class='muted'>");
    page += String(size / 1024.0f, 1);
    page += F(" kB</span> <form method='post' action='/delete' style='display:inline'>");
    page += F("<input type='hidden' name='name' value='");
    page += displayName;
    page += F("'><button class='del'>Usun</button></form></li>");
  }
  page += F("</ul></section>");
  page += F("<section><h2>Wgraj z komputera</h2><form method='post' action='/upload' enctype='multipart/form-data'>");
  page += F("<input type='file' name='gif' accept='.gif,image/gif' required> <button>Wgraj GIF</button></form></section>");
  page += F("<section><h2>Pobierz z internetu</h2><form method='post' action='/download'>");
  page += F("<label>Bezposredni adres GIF</label><input type='url' name='url' placeholder='https://.../obraz.gif' required>");
  page += F("<label>Nazwa na karcie (opcjonalna)</label><input type='text' name='name' placeholder='obraz.gif'>");
  page += F("<button>Pobierz na SD</button></form><p class='muted'>Maksymalnie 6 MB. Obraz nie moze przekraczac 160x128 px.</p></section>");
  page += F("<section><h2>Wi-Fi</h2><form method='post' action='/wifi-reset'>");
  page += F("<button class='del'>Usun zapisane Wi-Fi</button></form></section></body></html>");
  server.send(200, "text/html; charset=utf-8", page);
}

void handleUploadData() {
  HTTPUpload &upload = server.upload();
  if (upload.status == UPLOAD_FILE_START) {
    uploadError = "";
    uploadTarget = safeGifPath(upload.filename);
    SD.remove(UPLOAD_TEMP_FILE);
    if (!uploadTarget.length()) {
      uploadError = "Nazwa musi konczyc sie na .gif";
      return;
    }
    uploadFile = SD.open(UPLOAD_TEMP_FILE, FILE_WRITE);
    if (!uploadFile) {
      uploadError = "Nie mozna zapisac na karcie SD";
      return;
    }
    showMessage(F("Wgrywanie GIF"), uploadTarget);
  } else if (upload.status == UPLOAD_FILE_WRITE) {
    if (uploadFile && !uploadError.length() && uploadFile.write(upload.buf, upload.currentSize) != upload.currentSize) {
      uploadError = "Blad zapisu na karcie SD";
    }
  } else if (upload.status == UPLOAD_FILE_END) {
    if (uploadFile) uploadFile.close();
    if (!uploadError.length() && upload.totalSize > 0) {
      SD.remove(uploadTarget);
      if (!SD.rename(UPLOAD_TEMP_FILE, uploadTarget)) uploadError = "Nie mozna zmienic nazwy pliku";
      else libraryDirty = true;
    } else SD.remove(UPLOAD_TEMP_FILE);
  } else if (upload.status == UPLOAD_FILE_ABORTED) {
    if (uploadFile) uploadFile.close();
    SD.remove(UPLOAD_TEMP_FILE);
    uploadError = "Wgrywanie przerwane";
  }
  yield();
}

void finishUpload() {
  if (uploadError.length()) {
    server.send(400, "text/plain; charset=utf-8", uploadError);
    return;
  }
  server.sendHeader("Location", "/");
  server.send(303);
}

bool downloadWithClient(WiFiClient &client, const String &url, const String &target, String &error) {
  HTTPClient http;
  http.setTimeout(15000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  if (!http.begin(client, url)) {
    error = "Niepoprawny adres URL";
    return false;
  }
  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    error = "HTTP " + String(code);
    http.end();
    return false;
  }
  const int announcedSize = http.getSize();
  if (announcedSize > static_cast<int>(MAX_DOWNLOAD_BYTES)) {
    error = "Plik przekracza 6 MB";
    http.end();
    return false;
  }
  SD.remove(UPLOAD_TEMP_FILE);
  File output = SD.open(UPLOAD_TEMP_FILE, FILE_WRITE);
  if (!output) {
    error = "Nie mozna zapisac na karcie SD";
    http.end();
    return false;
  }
  WiFiClient *stream = http.getStreamPtr();
  uint8_t buffer[768];
  uint32_t total = 0;
  uint32_t lastDataAt = millis();
  while (http.connected() && (announcedSize < 0 || total < static_cast<uint32_t>(announcedSize))) {
    const size_t available = stream->available();
    if (available) {
      const size_t wanted = min(available, sizeof(buffer));
      const int read = stream->readBytes(buffer, wanted);
      if (read > 0) {
        if (total + read > MAX_DOWNLOAD_BYTES || output.write(buffer, read) != static_cast<size_t>(read)) {
          error = total + read > MAX_DOWNLOAD_BYTES ? "Plik przekracza 6 MB" : "Blad zapisu na SD";
          break;
        }
        total += read;
        lastDataAt = millis();
      }
    } else {
      if (millis() - lastDataAt > 15000) {
        error = "Przekroczony czas pobierania";
        break;
      }
      delay(1);
    }
    yield();
  }
  output.close();
  http.end();
  if (!error.length() && announcedSize >= 0 && total != static_cast<uint32_t>(announcedSize)) {
    error = "Polaczenie przerwane przed koncem pliku";
  }
  if (!error.length() && total > 0) {
    SD.remove(target);
    if (SD.rename(UPLOAD_TEMP_FILE, target)) return true;
    error = "Nie mozna zapisac pliku docelowego";
  }
  SD.remove(UPLOAD_TEMP_FILE);
  if (!error.length()) error = "Pobrano pusty plik";
  return false;
}

void handleDownload() {
  const String url = server.arg("url");
  String name = server.arg("name");
  if (!name.length()) {
    name = url.substring(url.lastIndexOf('/') + 1);
    const int query = name.indexOf('?');
    if (query >= 0) name.remove(query);
  }
  const String target = safeGifPath(name);
  if ((!url.startsWith("http://") && !url.startsWith("https://")) || !target.length()) {
    server.send(400, "text/plain; charset=utf-8", "Podaj bezposredni URL i nazwe zakonczona .gif");
    return;
  }
  showMessage(F("Pobieranie GIF"), target);
  String error;
  bool ok = false;
  if (url.startsWith("https://")) {
    BearSSL::WiFiClientSecure client;
    client.setInsecure();
    ok = downloadWithClient(client, url, target, error);
  } else {
    WiFiClient client;
    ok = downloadWithClient(client, url, target, error);
  }
  if (!ok) {
    showMessage(F("Blad pobierania"), error);
    server.send(502, "text/plain; charset=utf-8", error);
    return;
  }
  libraryDirty = true;
  server.sendHeader("Location", "/");
  server.send(303);
}

void startWebServer() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/upload", HTTP_POST, finishUpload, handleUploadData);
  server.on("/delete", HTTP_POST, []() {
    const String path = safeGifPath(server.arg("name"));
    if (!path.length() || !SD.remove(path)) {
      server.send(404, "text/plain; charset=utf-8", "Nie znaleziono pliku");
      return;
    }
    libraryDirty = true;
    server.sendHeader("Location", "/");
    server.send(303);
  });
  server.on("/download", HTTP_POST, handleDownload);
  server.on("/wifi-reset", HTTP_POST, []() {
    server.send(200, "text/plain; charset=utf-8", "Usunieto ustawienia Wi-Fi. Ramka uruchomi sie ponownie.");
    delay(300);
    wifiManager.resetSettings();
    ESP.restart();
  });
  server.onNotFound([]() {
    server.sendHeader("Location", "/");
    server.send(302);
  });
  server.begin();
  Serial.println(F("Serwer WWW uruchomiony"));
}

void startWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.hostname(HOST_NAME);
  wifiManager.setConnectTimeout(15);
  wifiManager.setConfigPortalTimeout(180);
  showMessage(F("Laczenie z Wi-Fi"), String("AP: ") + WIFI_AP_NAME + "\nhaslo: " + WIFI_AP_PASSWORD);
  if (!wifiManager.autoConnect(WIFI_AP_NAME, WIFI_AP_PASSWORD)) {
    networkReady = false;
    showMessage(F("Tryb offline"), "Restart, aby sprobowac Wi-Fi");
    Serial.println(F("Wi-Fi niedostepne - tryb offline"));
    delay(1200);
    return;
  }
  networkReady = true;
  mdnsReady = MDNS.begin(HOST_NAME);
  if (mdnsReady) MDNS.addService("http", "tcp", 80);
  startWebServer();
  const String address = String("http://ramka.local\n") + WiFi.localIP().toString();
  showMessage(F("Wi-Fi OK"), address);
  Serial.print(F("Panel: http://ramka.local lub http://"));
  Serial.println(WiFi.localIP());
  delay(1800);
}

void setup() {
  Serial.begin(115200);
  delay(50);
  pinMode(TFT_CS, OUTPUT);
  pinMode(SD_CARD_CS, OUTPUT);
  pinMode(ENCODER_CLK, INPUT_PULLUP);
  pinMode(ENCODER_DT, INPUT_PULLUP);
  pinMode(ENCODER_SW, INPUT_PULLUP);
  digitalWrite(TFT_CS, HIGH);
  digitalWrite(SD_CARD_CS, HIGH);
  attachInterrupt(digitalPinToInterrupt(ENCODER_CLK), onEncoderTurn, FALLING);
  attachInterrupt(digitalPinToInterrupt(ENCODER_SW), onEncoderButton, FALLING);
  SPI.begin();
  tft.initR(INITR_BLACKTAB);
  tft.setRotation(1);
  tft.fillScreen(ST77XX_BLACK);
  if (!SD.begin(SD_CARD_CS)) {
    showMessage(F("Brak karty SD"), "FAT32 / sprawdz kable");
    Serial.println(F("Nie mozna uruchomic karty SD"));
    while (true) delay(1000);
  }
  gif.begin(LITTLE_ENDIAN_PIXELS);
  scanGifFiles();
  showMessage(F("Karta SD OK"), String("GIF: ") + gifCount);
  delay(700);
  startWifi();
}

void loop() {
  static int index = 0;
  static bool emptyMessageShown = false;
  serviceNetwork();
  if (libraryDirty) {
    scanGifFiles();
    if (index >= gifCount) index = 0;
    emptyMessageShown = false;
  }
  if (gifCount == 0) {
    if (!emptyMessageShown) {
      showMessage(F("Brak plikow GIF"), networkReady ? "Otworz ramka.local" : "Wloz pliki na karte SD");
      emptyMessageShown = true;
    }
    serviceNetwork();
    delay(2);
    return;
  }

  const String currentPath = gifFiles[index];
  playFor(currentPath.c_str(), SHOW_TIME_MS);
  if (libraryDirty) return;
  if (encoderStep != 0) {
    noInterrupts();
    const int8_t step = encoderStep;
    encoderStep = 0;
    interrupts();
    index = (index + step + gifCount) % gifCount;
    Serial.println(step > 0 ? F("Enkoder: +1") : F("Enkoder: -1"));
  } else if (autoPlayChanged) {
    showMessage(autoPlay ? F("AUTO: ON") : F("AUTO: OFF"));
    Serial.println(autoPlay ? F("AUTO: ON") : F("AUTO: OFF"));
    delay(500);
    autoPlayChanged = false;
  } else if (autoPlay) {
    index = (index + 1) % gifCount;
  }
}
