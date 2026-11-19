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
constexpr uint32_t ENCODER_DEBOUNCE_US = 10000;
constexpr uint32_t ENCODER_DIRECTION_RESET_US = 600000;
constexpr uint32_t BUTTON_DEBOUNCE_MS = 35;
constexpr uint32_t BUTTON_LONG_PRESS_MS = 3000;
constexpr uint8_t MAX_GIFS = 64;
constexpr uint8_t MAX_FOLDERS = 12;
constexpr uint8_t MAX_TAGS = 24;
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
uint8_t activeFileIndexes[MAX_GIFS];
uint8_t activeCount = 0;
String gifFolders[MAX_FOLDERS];
uint8_t folderCount = 0;
String gifTags[MAX_TAGS];
uint8_t tagCount = 0;
String selectedFolder;
String selectedTag;
bool randomOrder = false;
int16_t gifX = 0;
int16_t gifY = 0;
volatile int8_t encoderStep = 0;
volatile uint32_t lastEncoderUs = 0;
volatile uint32_t lastEncoderAcceptedUs = 0;
volatile int8_t encoderDirection = 0;
volatile int8_t reverseCandidate = 0;
volatile uint8_t reverseCandidateCount = 0;
bool autoPlay = true;
bool buttonRawDown = false;
bool buttonStableDown = false;
bool buttonLongHandled = false;
bool buttonShortPress = false;
bool buttonLongPress = false;
uint32_t buttonChangedAtMs = 0;
uint32_t buttonPressedAtMs = 0;
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
  if (now - lastEncoderUs < ENCODER_DEBOUNCE_US || encoderStep != 0) return;
  lastEncoderUs = now;
  const int8_t candidate = digitalRead(ENCODER_DT) ? 1 : -1;

  // Podczas ciaglego obrotu kierunek pozostaje zablokowany. Zmiane kierunku
  // przyjmujemy dopiero po przerwie i dwoch zgodnych przeciwnych impulsach.
  if (encoderDirection == 0 || candidate == encoderDirection) {
    encoderDirection = candidate;
    reverseCandidate = 0;
    reverseCandidateCount = 0;
    encoderStep = candidate;
    lastEncoderAcceptedUs = now;
  } else {
    if (now - lastEncoderAcceptedUs < ENCODER_DIRECTION_RESET_US) {
      reverseCandidate = 0;
      reverseCandidateCount = 0;
      return;
    }
    if (reverseCandidate == candidate) {
      ++reverseCandidateCount;
    } else {
      reverseCandidate = candidate;
      reverseCandidateCount = 1;
    }
    if (reverseCandidateCount >= 2) {
      encoderDirection = candidate;
      reverseCandidate = 0;
      reverseCandidateCount = 0;
      encoderStep = candidate;
      lastEncoderAcceptedUs = now;
    }
  }
}

void updateButton() {
  const uint32_t now = millis();
  const bool rawDown = digitalRead(ENCODER_SW) == LOW;
  if (rawDown != buttonRawDown) {
    buttonRawDown = rawDown;
    buttonChangedAtMs = now;
  }
  if (now - buttonChangedAtMs >= BUTTON_DEBOUNCE_MS && rawDown != buttonStableDown) {
    buttonStableDown = rawDown;
    if (buttonStableDown) {
      buttonPressedAtMs = now;
      buttonLongHandled = false;
    } else if (!buttonLongHandled) {
      buttonShortPress = true;
    }
  }
  if (buttonStableDown && !buttonLongHandled &&
      now - buttonPressedAtMs >= BUTTON_LONG_PRESS_MS) {
    buttonLongHandled = true;
    buttonLongPress = true;
  }
}

int8_t takeEncoderStep() {
  noInterrupts();
  const int8_t step = encoderStep;
  encoderStep = 0;
  interrupts();
  return step;
}

bool pollControls() {
  updateButton();
  if (buttonShortPress || buttonLongPress) {
    noInterrupts();
    encoderStep = 0;
    interrupts();
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

String cleanPathPart(const String &value, uint8_t maxLength) {
  String clean;
  clean.reserve(maxLength);
  for (uint16_t i = 0; i < value.length() && clean.length() < maxLength; ++i) {
    const char c = value[i];
    if (isalnum(static_cast<unsigned char>(c)) || c == '.' || c == '-' || c == '_') clean += c;
    else if (c == ' ') clean += '_';
  }
  return clean;
}

String safeGifPath(String name) {
  name.replace('\\', '/');
  while (name.startsWith("/")) name.remove(0, 1);
  if (name.indexOf("..") >= 0) return "";
  const int slash = name.indexOf('/');
  String folder;
  String fileName = name;
  if (slash >= 0) {
    if (name.indexOf('/', slash + 1) >= 0) return "";
    folder = cleanPathPart(name.substring(0, slash), 24);
    fileName = name.substring(slash + 1);
    if (!folder.length()) return "";
  }
  const String clean = cleanPathPart(fileName, 52);
  String lower = clean;
  lower.toLowerCase();
  if (!lower.endsWith(".gif") || clean.length() < 5) return "";
  return folder.length() ? "/" + folder + "/" + clean : "/" + clean;
}

String htmlEscape(String value) {
  value.replace("&", "&amp;");
  value.replace("<", "&lt;");
  value.replace(">", "&gt;");
  value.replace("\"", "&quot;");
  value.replace("'", "&#39;");
  return value;
}

String jsonEscape(String value) {
  value.replace("\\", "\\\\");
  value.replace("\"", "\\\"");
  value.replace("\r", "\\r");
  value.replace("\n", "\\n");
  return value;
}

String baseNameFromPath(const String &path) {
  const int slash = path.lastIndexOf('/');
  return slash >= 0 ? path.substring(slash + 1) : path;
}

String folderFromPath(const String &path) {
  const int slash = path.lastIndexOf('/');
  return slash <= 0 ? "/" : path.substring(0, slash);
}

String displayNameFromPath(const String &path) {
  String name = baseNameFromPath(path);
  const int extension = name.lastIndexOf('.');
  if (extension > 0) name.remove(extension);
  const int tags = name.indexOf("__");
  if (tags >= 0) name.remove(tags);
  return name;
}

bool isGifName(String name) {
  name.toLowerCase();
  return name.endsWith(".gif");
}

void addFolder(const String &folder) {
  for (uint8_t i = 0; i < folderCount; ++i) {
    if (gifFolders[i] == folder) return;
  }
  if (folderCount < MAX_FOLDERS) gifFolders[folderCount++] = folder;
}

void addTag(String tag) {
  tag.trim();
  tag.toLowerCase();
  if (!tag.length()) return;
  for (uint8_t i = 0; i < tagCount; ++i) {
    if (gifTags[i] == tag) return;
  }
  if (tagCount < MAX_TAGS) gifTags[tagCount++] = tag;
}

void collectTags(const String &path) {
  String name = baseNameFromPath(path);
  const int marker = name.indexOf("__");
  if (marker < 0) return;
  const int extension = name.lastIndexOf('.');
  String tags = name.substring(marker + 2, extension > marker ? extension : name.length());
  int start = 0;
  while (start < static_cast<int>(tags.length())) {
    int end = tags.indexOf('_', start);
    if (end < 0) end = tags.length();
    addTag(tags.substring(start, end));
    start = end + 1;
  }
}

bool fileHasTag(const String &path, const String &wantedTag) {
  if (!wantedTag.length()) return true;
  String name = baseNameFromPath(path);
  const int marker = name.indexOf("__");
  if (marker < 0) return false;
  const int extension = name.lastIndexOf('.');
  String tags = name.substring(marker + 2, extension > marker ? extension : name.length());
  tags.toLowerCase();
  int start = 0;
  while (start < static_cast<int>(tags.length())) {
    int end = tags.indexOf('_', start);
    if (end < 0) end = tags.length();
    if (tags.substring(start, end) == wantedTag) return true;
    start = end + 1;
  }
  return false;
}

void addGifPath(String path) {
  path.replace('\\', '/');
  if (!path.startsWith("/")) path = "/" + path;
  if (gifCount >= MAX_GIFS || !isGifName(path)) return;
  gifFiles[gifCount++] = path;
  collectTags(path);
}

void shuffleActiveFiles(int previousLibraryIndex = -1) {
  if (!randomOrder || activeCount < 2) return;
  for (int i = activeCount - 1; i > 0; --i) {
    const int j = random(i + 1);
    const uint8_t tmp = activeFileIndexes[i];
    activeFileIndexes[i] = activeFileIndexes[j];
    activeFileIndexes[j] = tmp;
  }
  if (previousLibraryIndex >= 0 && activeFileIndexes[0] == previousLibraryIndex) {
    const uint8_t tmp = activeFileIndexes[0];
    activeFileIndexes[0] = activeFileIndexes[1];
    activeFileIndexes[1] = tmp;
  }
}

int rebuildActiveList(int preserveLibraryIndex = -1) {
  activeCount = 0;
  for (uint8_t i = 0; i < gifCount; ++i) {
    const bool folderMatches = !selectedFolder.length() || folderFromPath(gifFiles[i]) == selectedFolder;
    if (folderMatches && fileHasTag(gifFiles[i], selectedTag)) {
      activeFileIndexes[activeCount++] = i;
    }
  }
  shuffleActiveFiles();
  for (uint8_t i = 0; i < activeCount; ++i) {
    if (activeFileIndexes[i] == preserveLibraryIndex) return i;
  }
  return activeCount ? 0 : -1;
}

const String &activePath(int index) {
  return gifFiles[activeFileIndexes[index]];
}

void sortLibraryLabels() {
  for (uint8_t i = 0; i < gifCount; ++i) {
    for (uint8_t j = i + 1; j < gifCount; ++j) {
      if (gifFiles[j].compareTo(gifFiles[i]) < 0) {
        const String tmp = gifFiles[i]; gifFiles[i] = gifFiles[j]; gifFiles[j] = tmp;
      }
    }
  }
  for (uint8_t i = 0; i < folderCount; ++i) {
    for (uint8_t j = i + 1; j < folderCount; ++j) {
      if (gifFolders[j].compareTo(gifFolders[i]) < 0) {
        const String tmp = gifFolders[i]; gifFolders[i] = gifFolders[j]; gifFolders[j] = tmp;
      }
    }
  }
  for (uint8_t i = 0; i < tagCount; ++i) {
    for (uint8_t j = i + 1; j < tagCount; ++j) {
      if (gifTags[j].compareTo(gifTags[i]) < 0) {
        const String tmp = gifTags[i]; gifTags[i] = gifTags[j]; gifTags[j] = tmp;
      }
    }
  }
}

void scanGifFiles() {
  gifCount = 0;
  folderCount = 0;
  tagCount = 0;
  File root = SD.open("/");
  if (!root) {
    activeCount = 0;
    libraryDirty = false;
    return;
  }
  File entry = root.openNextFile();
  while (entry && gifCount < MAX_GIFS) {
    if (entry.isDirectory()) {
      const String folder = "/" + baseNameFromPath(entry.name());
      File directory = SD.open(folder);
      if (directory) {
        File child = directory.openNextFile();
        while (child && gifCount < MAX_GIFS) {
          if (!child.isDirectory() && child.size() > 0 && isGifName(child.name())) {
            addFolder(folder);
            addGifPath(folder + "/" + baseNameFromPath(child.name()));
          }
          child.close();
          child = directory.openNextFile();
          yield();
        }
        directory.close();
      }
    } else if (entry.size() > 0 && isGifName(entry.name())) {
      addGifPath("/" + baseNameFromPath(entry.name()));
    }
    entry.close();
    entry = root.openNextFile();
    yield();
  }
  root.close();
  sortLibraryLabels();
  rebuildActiveList();
  libraryDirty = false;
  Serial.printf("Biblioteka: %u GIF, %u folderow, %u tagow, aktywne: %u\n",
                gifCount, folderCount, tagCount, activeCount);
}

void prepareMenuControls() {
  buttonShortPress = false;
  buttonLongPress = false;
  noInterrupts();
  encoderStep = 0;
  encoderDirection = 0;
  reverseCandidate = 0;
  reverseCandidateCount = 0;
  interrupts();
}

void drawFileMenu(int selected) {
  constexpr uint8_t visibleRows = 9;
  const int first = selected < visibleRows ? 0 : selected - visibleRows + 1;
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(1);
  tft.setTextWrap(false);
  tft.setTextColor(ST77XX_YELLOW);
  tft.setCursor(3, 4);
  tft.print(F("WYBIERZ GIF  "));
  tft.print(selected + 1); tft.print('/'); tft.print(activeCount);
  tft.drawFastHLine(0, 14, SCREEN_WIDTH, ST77XX_BLUE);
  for (uint8_t row = 0; row < visibleRows; ++row) {
    const int fileIndex = first + row;
    if (fileIndex >= activeCount) break;
    const int16_t y = 18 + row * 12;
    const bool active = fileIndex == selected;
    if (active) tft.fillRect(0, y - 2, SCREEN_WIDTH, 11, ST77XX_BLUE);
    tft.setTextColor(active ? ST77XX_WHITE : ST77XX_CYAN);
    tft.setCursor(3, y); tft.print(active ? '>' : ' ');
    String name = displayNameFromPath(activePath(fileIndex));
    if (name.length() > 23) name = name.substring(0, 22) + '~';
    tft.print(name);
  }
}

int selectGifFromMenu(int currentIndex) {
  if (activeCount == 0) return -1;
  int selected = constrain(currentIndex, 0, activeCount - 1);
  prepareMenuControls();
  drawFileMenu(selected);
  while (true) {
    serviceNetwork(); updateButton();
    const int8_t step = takeEncoderStep();
    if (step != 0) {
      selected = (selected + step + activeCount) % activeCount;
      drawFileMenu(selected);
    }
    if (buttonShortPress) {
      buttonShortPress = false;
      return selected;
    }
    if (buttonLongPress) {
      buttonLongPress = false;
      return -1;
    }
    delay(2);
  }
}

String sourceLabel() {
  if (!selectedFolder.length()) return "Wszystkie";
  if (selectedFolder == "/") return "Glowny";
  return selectedFolder.substring(1);
}

void drawChoiceMenu(const __FlashStringHelper *title, int selected, bool folders) {
  const int count = folders ? folderCount + 2 : tagCount + 1;
  constexpr uint8_t visibleRows = 8;
  const int first = selected < visibleRows ? 0 : selected - visibleRows + 1;
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(1); tft.setTextWrap(false); tft.setTextColor(ST77XX_YELLOW);
  tft.setCursor(3, 4); tft.print(title);
  tft.drawFastHLine(0, 14, SCREEN_WIDTH, ST77XX_BLUE);
  for (uint8_t row = 0; row < visibleRows; ++row) {
    const int item = first + row;
    if (item >= count) break;
    const int16_t y = 20 + row * 13;
    const bool active = item == selected;
    if (active) tft.fillRect(0, y - 2, SCREEN_WIDTH, 12, ST77XX_BLUE);
    tft.setTextColor(active ? ST77XX_WHITE : ST77XX_CYAN);
    tft.setCursor(3, y); tft.print(active ? '>' : ' ');
    String label;
    if (folders) {
      if (item == 0) label = "Wszystkie";
      else if (item == 1) label = "Glowny";
      else label = gifFolders[item - 2].substring(1);
    } else label = item == 0 ? "Bez filtra" : gifTags[item - 1];
    if (label.length() > 23) label = label.substring(0, 22) + '~';
    tft.print(label);
  }
}

int chooseLibraryFilter(bool folders) {
  const int count = folders ? folderCount + 2 : tagCount + 1;
  int selected = 0;
  if (folders) {
    if (selectedFolder == "/") selected = 1;
    else for (uint8_t i = 0; i < folderCount; ++i) if (gifFolders[i] == selectedFolder) selected = i + 2;
  } else {
    for (uint8_t i = 0; i < tagCount; ++i) if (gifTags[i] == selectedTag) selected = i + 1;
  }
  prepareMenuControls();
  drawChoiceMenu(folders ? F("ZRODLO") : F("TAG"), selected, folders);
  while (true) {
    serviceNetwork(); updateButton();
    const int8_t step = takeEncoderStep();
    if (step != 0) {
      selected = (selected + step + count) % count;
      drawChoiceMenu(folders ? F("ZRODLO") : F("TAG"), selected, folders);
    }
    if (buttonShortPress) { buttonShortPress = false; return selected; }
    if (buttonLongPress) { buttonLongPress = false; return -1; }
    delay(2);
  }
}

void drawLibraryMenu(int selected) {
  const String values[] = {
    sourceLabel(),
    selectedTag.length() ? selectedTag : "Brak",
    randomOrder ? "Losowo" : "Po kolei",
    "Otworz liste",
    "Powrot"
  };
  const __FlashStringHelper *labels[] = {F("Zrodlo"), F("Tag"), F("Kolejnosc"), F("Plik"), F("Gotowe")};
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(1); tft.setTextWrap(false); tft.setTextColor(ST77XX_YELLOW);
  tft.setCursor(3, 4); tft.print(F("BIBLIOTEKA"));
  tft.drawFastHLine(0, 14, SCREEN_WIDTH, ST77XX_BLUE);
  for (uint8_t row = 0; row < 5; ++row) {
    const int16_t y = 22 + row * 20;
    const bool active = row == selected;
    if (active) tft.fillRect(0, y - 3, SCREEN_WIDTH, 18, ST77XX_BLUE);
    tft.setTextColor(active ? ST77XX_WHITE : ST77XX_CYAN);
    tft.setCursor(3, y); tft.print(active ? '>' : ' '); tft.print(labels[row]);
    if (row < 4) {
      String value = values[row];
      if (value.length() > 12) value = value.substring(0, 11) + '~';
      tft.setCursor(82, y); tft.print(value);
    }
  }
}

bool openLibraryMenu(int &currentIndex) {
  int selected = 0;
  prepareMenuControls();
  drawLibraryMenu(selected);
  while (true) {
    serviceNetwork(); updateButton();
    if (libraryDirty) {
      scanGifFiles(); currentIndex = 0; drawLibraryMenu(selected);
    }
    const int8_t step = takeEncoderStep();
    if (step != 0) {
      selected = (selected + step + 5) % 5;
      drawLibraryMenu(selected);
    }
    if (buttonLongPress) { buttonLongPress = false; return false; }
    if (!buttonShortPress) { delay(2); continue; }
    buttonShortPress = false;
    const int preserved = activeCount ? activeFileIndexes[constrain(currentIndex, 0, activeCount - 1)] : -1;
    if (selected == 0) {
      const int choice = chooseLibraryFilter(true);
      if (choice >= 0) {
        selectedFolder = choice == 0 ? "" : choice == 1 ? "/" : gifFolders[choice - 2];
        currentIndex = rebuildActiveList(preserved);
      }
    } else if (selected == 1) {
      const int choice = chooseLibraryFilter(false);
      if (choice >= 0) {
        selectedTag = choice == 0 ? "" : gifTags[choice - 1];
        currentIndex = rebuildActiveList(preserved);
      }
    } else if (selected == 2) {
      randomOrder = !randomOrder;
      currentIndex = rebuildActiveList(preserved);
    } else if (selected == 3) {
      const int choice = selectGifFromMenu(currentIndex < 0 ? 0 : currentIndex);
      if (choice >= 0) { currentIndex = choice; return true; }
    } else return false;
    if (currentIndex < 0) currentIndex = 0;
    prepareMenuControls();
    drawLibraryMenu(selected);
  }
}

bool playTimeRemaining(uint32_t startedAt, uint32_t durationMs) {
  return durationMs == 0 || millis() - startedAt < durationMs;
}

void playFor(const char *path, uint32_t durationMs) {
  const uint32_t startedAt = millis();
  tft.fillScreen(ST77XX_BLACK);
  while (playTimeRemaining(startedAt, durationMs)) {
    if (!openGif(path)) {
      showMessage(F("Niepoprawny GIF"), path);
      delay(1200);
      return;
    }
    uint16_t frameCount = 0;
    while (playTimeRemaining(startedAt, durationMs)) {
      // playFrame() zwraca 0 także wtedy, gdy właśnie narysował ostatnią
      // klatkę. Liczenie tylko wartości true powodowało, że GIF z dwiema
      // klatkami był błędnie uznawany za obraz jednoklatkowy.
      const int playResult = gif.playFrame(true, nullptr);
      if (playResult < 0) break;
      if (gif.getLastError() == GIF_SUCCESS) ++frameCount;
      serviceNetwork();
      if (pollControls() || libraryDirty) {
        gif.close();
        return;
      }
      if (playResult == 0) break;
      yield();
    }
    gif.close();
    // Jednoklatkowy GIF zostaje w pamieci kontrolera ST7735.
    if (frameCount <= 1) {
      while (playTimeRemaining(startedAt, durationMs)) {
        serviceNetwork();
        if (pollControls() || libraryDirty) return;
        delay(1);
      }
      return;
    }
  }
}

const char PAGE_HTML[] PROGMEM = R"RAMKAPAGE(
<!doctype html><html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ramka</title>
<style>
body{font-family:system-ui;background:#111827;color:#f9fafb;max-width:760px;margin:auto;padding:20px}
section{background:#1f2937;padding:18px;border-radius:14px;margin:14px 0}h1{margin:0 0 4px}h2{margin-top:0}
input,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #4b5563;margin:4px 0}
input[type=text],input[type=url]{width:calc(100% - 22px);background:#111827;color:white}
button,.btn{display:inline-block;background:#22c55e;color:#052e16;font-weight:700;cursor:pointer;text-decoration:none;padding:10px;border-radius:8px;border:0}
.del{background:#ef4444;color:white}ul{padding:0;list-style:none}
li{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px 0;border-bottom:1px solid #374151}
.name{overflow-wrap:anywhere;flex:1 1 280px}.muted{color:#9ca3af}code{color:#67e8f9}label{display:block;margin-top:8px}
@media(max-width:520px){body{padding:12px}section{padding:14px}}
</style></head><body>
<h1>Ramka ESP8266</h1><div class="muted">Panel <code>ramka.local</code></div>
<section><h2>Wgraj z komputera</h2><form method="post" action="/upload" enctype="multipart/form-data">
<input type="file" name="gif" accept=".gif,image/gif" required>
<label>Folder na karcie (opcjonalny)</label><input type="text" name="folder" placeholder="np. rodzina">
<button>Wgraj GIF</button></form></section>
<section><h2>Pobierz z internetu</h2><form method="post" action="/download">
<label>Bezposredni adres GIF</label><input type="url" name="url" placeholder="https://.../obraz.gif" required>
<label>Nazwa na karcie (opcjonalna)</label><input type="text" name="name" placeholder="obraz.gif">
<button>Pobierz na SD</button></form><p class="muted">Maksymalnie 6 MB. Obraz nie moze przekraczac 160x128 px.</p></section>
<section><h2>Animacje na karcie <span id="count" class="muted"></span></h2><ul id="files"><li>Ladowanie...</li></ul></section>
<section><h2>Wi-Fi</h2><form method="post" action="/wifi-reset"><button class="del">Usun zapisane Wi-Fi</button></form></section>
<script>
async function loadFiles(){
 const list=document.getElementById('files');
 try{
  const response=await fetch('/api/files',{cache:'no-store'});
  if(!response.ok)throw new Error('HTTP '+response.status);
  const data=await response.json();document.getElementById('count').textContent='('+data.files.length+')';list.replaceChildren();
  if(!data.files.length){const li=document.createElement('li');li.textContent='Brak plikow GIF';list.append(li);return}
  for(const file of data.files){
   const li=document.createElement('li'),info=document.createElement('span'),title=document.createElement('b'),size=document.createElement('span');
   info.className='name';title.textContent=file.name;size.className='muted';size.textContent=' '+(file.size/1024).toFixed(1)+' kB';info.append(title,size);
   const download=document.createElement('a');download.className='btn';download.textContent='Pobierz';download.href='/file?name='+encodeURIComponent(file.name);
   const form=document.createElement('form');form.method='post';form.action='/delete';
   const hidden=document.createElement('input');hidden.type='hidden';hidden.name='name';hidden.value=file.name;
   const remove=document.createElement('button');remove.className='del';remove.textContent='Usun';form.append(hidden,remove);li.append(info,download,form);list.append(li)
  }
 }catch(error){list.innerHTML='<li>Nie mozna pobrac listy: '+error.message+'</li>'}
}
loadFiles();
</script></body></html>
)RAMKAPAGE";

void handleRoot() {
  // Stala strona jest czytana prosto z flash. Lista plikow jest pobierana
  // osobno z lekkiego API, wiec liczba GIF-ow nie zuzywa RAM-u ESP8266.
  server.send_P(200, PSTR("text/html; charset=utf-8"), PAGE_HTML);
}

void handleUploadData() {
  HTTPUpload &upload = server.upload();
  if (upload.status == UPLOAD_FILE_START) {
    uploadError = "";
    uploadTarget = safeGifPath(upload.filename);
    const String requestedFolder = server.arg("folder");
    if (requestedFolder.length()) {
      const String folder = cleanPathPart(requestedFolder, 24);
      if (!folder.length() || folder != requestedFolder) {
        uploadError = "Niepoprawna nazwa folderu";
        return;
      }
      const String folderPath = "/" + folder;
      if (!SD.exists(folderPath) && !SD.mkdir(folderPath)) {
        uploadError = "Nie mozna utworzyc folderu";
        return;
      }
      uploadTarget = folderPath + uploadTarget;
    }
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

void handleApiFiles() {
  String json = "{\"files\":[";
  for (uint8_t i = 0; i < gifCount; ++i) {
    if (i > 0) json += ',';
    File file = SD.open(gifFiles[i], FILE_READ);
    const uint32_t size = file ? file.size() : 0;
    file.close();
    json += "{\"name\":\"";
    json += jsonEscape(gifFiles[i].substring(1));
    json += "\",\"size\":";
    json += String(size);
    json += '}';
    yield();
  }
  json += "]}";
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json; charset=utf-8", json);
}

void handleFileDownload() {
  const String path = safeGifPath(server.arg("name"));
  if (!path.length()) {
    server.send(400, "text/plain; charset=utf-8", "Niepoprawna nazwa pliku");
    return;
  }
  File file = SD.open(path, FILE_READ);
  if (!file) {
    server.send(404, "text/plain; charset=utf-8", "Nie znaleziono pliku");
    return;
  }
  server.sendHeader("Content-Disposition", "attachment; filename=\"" + baseNameFromPath(path) + "\"");
  server.sendHeader("Cache-Control", "no-store");
  server.streamFile(file, "image/gif");
  file.close();
}

void startWebServer() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/api/files", HTTP_GET, handleApiFiles);
  server.on("/file", HTTP_GET, handleFileDownload);
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
  buttonRawDown = digitalRead(ENCODER_SW) == LOW;
  buttonStableDown = buttonRawDown;
  buttonChangedAtMs = millis();
  buttonPressedAtMs = millis();
  buttonLongHandled = buttonStableDown;
  digitalWrite(TFT_CS, HIGH);
  digitalWrite(SD_CARD_CS, HIGH);
  attachInterrupt(digitalPinToInterrupt(ENCODER_CLK), onEncoderTurn, FALLING);
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
  randomSeed(ESP.getCycleCount() ^ micros());
  scanGifFiles();
  showMessage(F("Karta SD OK"), String("GIF: ") + gifCount + " / aktywne: " + activeCount);
  delay(700);
  startWifi();
}

void loop() {
  static int index = 0;
  static bool emptyMessageShown = false;
  serviceNetwork();
  if (libraryDirty) {
    scanGifFiles();
    if (index >= activeCount) index = 0;
    emptyMessageShown = false;
  }
  if (activeCount == 0) {
    if (!emptyMessageShown) {
      showMessage(gifCount == 0 ? F("Brak plikow GIF") : F("Brak dla filtra"),
                  gifCount == 0 ? "Wloz pliki na karte SD" : "Przytrzymaj 3 sekundy");
      emptyMessageShown = true;
    }
    serviceNetwork();
    updateButton();
    if (buttonLongPress) {
      buttonLongPress = false;
      openLibraryMenu(index);
      emptyMessageShown = false;
    }
    delay(2);
    return;
  }

  const String currentPath = activePath(index);
  playFor(currentPath.c_str(), autoPlay ? SHOW_TIME_MS : 0);
  if (libraryDirty) return;
  if (buttonLongPress) {
    buttonLongPress = false;
    const bool fileSelected = openLibraryMenu(index);
    if (fileSelected && activeCount > 0) {
      autoPlay = false;
      showMessage(F("TRYB: WYBRANY"), displayNameFromPath(activePath(index)));
      delay(600);
    }
  } else if (buttonShortPress) {
    buttonShortPress = false;
    autoPlay = !autoPlay;
    showMessage(autoPlay ? F("TRYB: PO KOLEI") : F("TRYB: WYBRANY"),
                displayNameFromPath(activePath(index)));
    Serial.println(autoPlay ? F("Tryb: po kolei") : F("Tryb: tylko wybrany"));
    delay(600);
  } else if (encoderStep != 0) {
    const int8_t step = takeEncoderStep();
    index = (index + step + activeCount) % activeCount;
    Serial.println(step > 0 ? F("Enkoder: +1") : F("Enkoder: -1"));
  } else if (autoPlay) {
    if (index + 1 < activeCount) ++index;
    else {
      const int previousLibraryIndex = activeFileIndexes[index];
      shuffleActiveFiles(previousLibraryIndex);
      index = 0;
    }
  }
}
