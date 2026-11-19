#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <AnimatedGIF.h>

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

struct Animation {
  const char *name;
  const char *file;
  bool animated;
};

const Animation ANIMATIONS[] = {
    {"Nyan Cat", "/nyan.gif", false},
    {"Zachod slonca", "/sunset.gif", false},
    {"Kot w kosmosie", "/catspace.gif", true},
};

constexpr int ANIMATION_COUNT = sizeof(ANIMATIONS) / sizeof(ANIMATIONS[0]);

Adafruit_ST7735 tft(TFT_CS, TFT_DC, TFT_RST);
AnimatedGIF gif;
File gifFile;
// ESP8266 SPI czyta dane blokami 32-bitowymi. Wymuszenie wyrownania do 4 bajtow
// zapobiega Exception (9) w SPIClass::writeBytes_().
alignas(4) uint16_t scanline[SCREEN_WIDTH];
int16_t gifX = 0;
int16_t gifY = 0;
volatile int8_t encoderStep = 0;
volatile bool encoderButtonPressed = false;
volatile uint32_t lastEncoderUs = 0;
volatile uint32_t lastButtonUs = 0;
bool autoPlay = true;
bool autoPlayChanged = false;

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
  if (now - lastEncoderUs < 2500) {
    return;
  }
  lastEncoderUs = now;
  encoderStep = digitalRead(ENCODER_DT) ? 1 : -1;
}

void IRAM_ATTR onEncoderButton() {
  const uint32_t now = micros();
  if (now - lastButtonUs < 50000) {
    return;
  }
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

void *gifOpen(const char *filename, int32_t *size) {
  gifFile = SD.open(filename, FILE_READ);
  if (!gifFile) {
    return nullptr;
  }
  *size = static_cast<int32_t>(gifFile.size());
  return &gifFile;
}

void gifClose(void *handle) {
  File *file = static_cast<File *>(handle);
  if (file) {
    file->close();
  }
}

int32_t gifRead(GIFFILE *fileInfo, uint8_t *buffer, int32_t length) {
  File *file = static_cast<File *>(fileInfo->fHandle);
  if (!file || length <= 0) {
    return 0;
  }

  const int32_t remaining = fileInfo->iSize - fileInfo->iPos;
  if (length > remaining) {
    length = remaining;
  }
  const int32_t bytesRead = static_cast<int32_t>(file->read(buffer, length));
  fileInfo->iPos = static_cast<int32_t>(file->position());
  return bytesRead;
}

int32_t gifSeek(GIFFILE *fileInfo, int32_t position) {
  File *file = static_cast<File *>(fileInfo->fHandle);
  if (!file || !file->seek(position, SeekSet)) {
    return -1;
  }
  fileInfo->iPos = static_cast<int32_t>(file->position());
  return fileInfo->iPos;
}

void gifDraw(GIFDRAW *draw) {
  int16_t x = gifX + draw->iX;
  const int16_t y = gifY + draw->iY + draw->y;
  int16_t width = draw->iWidth;

  if (y < 0 || y >= SCREEN_HEIGHT || x >= SCREEN_WIDTH || x + width <= 0) {
    return;
  }

  uint8_t *pixels = draw->pPixels;
  if (x < 0) {
    pixels -= x;
    width += x;
    x = 0;
  }
  if (x + width > SCREEN_WIDTH) {
    width = SCREEN_WIDTH - x;
  }

  uint16_t *palette = draw->pPalette;
  if (!draw->ucHasTransparency) {
    for (int16_t i = 0; i < width; ++i) {
      scanline[i] = palette[pixels[i]];
    }
    tft.drawRGBBitmap(x, y, scanline, width, 1);
    return;
  }

  const uint8_t transparent = draw->ucTransparent;
  int16_t start = 0;
  while (start < width) {
    while (start < width && pixels[start] == transparent) {
      ++start;
    }
    int16_t end = start;
    while (end < width && pixels[end] != transparent) {
      scanline[end - start] = palette[pixels[end]];
      ++end;
    }
    if (end > start) {
      tft.drawRGBBitmap(x + start, y, scanline, end - start, 1);
    }
    start = end;
  }
}

bool fileExists(const char *path) {
  File file = SD.open(path, FILE_READ);
  if (!file) {
    return false;
  }
  const bool valid = file.size() > 0;
  file.close();
  return valid;
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

void playFor(const char *path, uint32_t durationMs, bool animated) {
  const uint32_t startedAt = millis();
  tft.fillScreen(ST77XX_BLACK);

  while (millis() - startedAt < durationMs) {
    if (!openGif(path)) {
      showMessage(F("Niepoprawny GIF"), path);
      delay(1500);
      return;
    }

    while (millis() - startedAt < durationMs && gif.playFrame(true, nullptr)) {
      if (pollControls()) {
        gif.close();
        return;
      }
      yield();
    }
    gif.close();

    // Obraz jednoklatkowy zostaje juz w pamieci kontrolera ST7735. Nie ma
    // potrzeby rysowac go bez przerwy; w tym czasie obslugujemy sterowanie.
    if (!animated) {
      while (millis() - startedAt < durationMs) {
        if (pollControls()) {
          return;
        }
        delay(1);
      }
      return;
    }
  }
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
    while (true) {
      delay(1000);
    }
  }

  gif.begin(LITTLE_ENDIAN_PIXELS);
  showMessage(F("Karta SD OK"));
  delay(800);
}

void loop() {
  static int index = 0;
  const Animation &animation = ANIMATIONS[index];

  if (fileExists(animation.file)) {
    playFor(animation.file, SHOW_TIME_MS, animation.animated);
  } else {
    showMessage(F("Brak pliku"), animation.file);
    Serial.printf("Brak pliku: %s\n", animation.file);
    delay(2000);
  }

  if (encoderStep != 0) {
    noInterrupts();
    const int8_t step = encoderStep;
    encoderStep = 0;
    interrupts();
    index = (index + step + ANIMATION_COUNT) % ANIMATION_COUNT;
    Serial.println(step > 0 ? F("Enkoder: +1") : F("Enkoder: -1"));
  } else if (autoPlayChanged) {
    showMessage(autoPlay ? F("AUTO: ON") : F("AUTO: OFF"));
    Serial.println(autoPlay ? F("AUTO: ON") : F("AUTO: OFF"));
    delay(700);
    autoPlayChanged = false;
  } else if (autoPlay) {
    index = (index + 1) % ANIMATION_COUNT;
  }
}
