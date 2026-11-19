# Ramka — ESP8266 + ST7735

ESP8266 odtwarza obrazy i animacje GIF zapisane na karcie microSD. Ekran pracuje
poziomo w rozdzielczości 160×128, a plik zmienia się co 12 sekund.

Do katalogu głównego karty skopiuj pliki przygotowane w folderze `gif`:

- `gif/nyan.gif` jako `/nyan.gif`;
- `gif/sunset.gif` jako `/sunset.gif`;
- `gif/cat-space-128.gif` pod nazwą `/catspace.gif`.

Pierwsze dwa to statyczne obrazy zapisane jako jednoklatkowe GIF-y, a trzeci jest
animowany. Po skopiowaniu urządzenie działa bez internetu.

## Połączenie

| ST7735 | ESP8266 / NodeMCU | Uwagi |
|---|---|---|
| VCC | 3V3 | Nie 5 V |
| GND | GND | |
| SCL / SCK | D5 (GPIO14) | sprzętowe SPI |
| SDA / MOSI | D7 (GPIO13) | sprzętowe SPI; to nie jest I²C |
| CS | D8 (GPIO15) | wybór ekranu |
| DC / A0 | D1 (GPIO5) | |
| RES / RESET | RST | bezpośrednio do pinu `RST` ESP8266 |
| BL / LED | 3V3 | opcjonalnie przez rezystor, jeśli moduł go nie ma |
| SD_SCK | D5 (GPIO14) | razem z pinem SCK ekranu |
| SD_MOSI | D7 (GPIO13) | razem z pinem SDA/MOSI ekranu |
| SD_MISO | D6 (GPIO12) | tylko karta SD |
| SD_CS | D4 (GPIO2) | osobny wybór karty |

Wyświetlacz i ESP8266 pracują z logiką 3,3 V. Nazwy pinów na różnych modułach
ST7735 bywają inne, dlatego przed podłączeniem warto porównać nadruki na płytce.
Na module ze zdjęcia piny ekranu są po lewej, a cztery piny `SD_*` po prawej.
Karta i ekran współdzielą D5 oraz D7, ale każdy ma osobny pin `CS`.

## Enkoder obrotowy

Dla modułu z opisami `CLK`, `DT`, `SW`, `+` i `GND`:

| Enkoder | ESP8266 | Funkcja |
|---|---|---|
| CLK | D2 (GPIO4) | obrót A |
| DT | D0 (GPIO16) | obrót B |
| SW | D3 (GPIO0) | przycisk |
| + / VCC | 3V3 | nigdy 5 V |
| GND | GND | wspólna masa |

Obrót wybiera poprzednią lub następną animację. Naciśnięcie przełącza automatyczną
zmianę animacji co 12 sekund. Jeśli kierunek obrotu jest odwrotny, zamień przewody
`CLK` i `DT`.

`D3` jest pinem startowym ESP8266. Nie trzymaj wciśniętego enkodera podczas
włączania zasilania ani resetowania płytki, bo ESP8266 może wejść w tryb programowania.
Jeśli jest to goły enkoder bez płytki i rezystorów, linia podłączona do D0 może
wymagać zewnętrznego rezystora podciągającego 10 kΩ do 3,3 V.

## Uruchomienie

1. Otwórz `ramka.ino` w Arduino IDE albo katalog projektu w VS Code z PlatformIO.
2. Włóż kartę microSD sformatowaną jako FAT32 (na początek najlepiej 4–32 GB).
3. W Arduino IDE wybierz `NodeMCU 1.0 (ESP-12E Module)` i właściwy port COM.
4. Zainstaluj biblioteki `Adafruit GFX Library`, `Adafruit ST7735 and ST7789
   Library` oraz `AnimatedGIF` autorstwa Larry Bank.
5. Zbuduj i wgraj szkic.

## Gdy ekran wygląda źle

- biały ekran: sprawdź zasilanie, CS, DC, RST, SCK i MOSI;
- przesunięte kolory/obraz: zamień `INITR_BLACKTAB` w `ramka.ino` na
  `INITR_GREENTAB` albo `INITR_REDTAB`;
- obraz obrócony: zmień `tft.setRotation(1)` na wartość 0, 2 lub 3;
- odwrócone kolory: po `initR` dodaj `tft.invertDisplay(true)`.

## Pliki

Lista nazw znajduje się w tablicy `ANIMATIONS` w `ramka.ino`. Użyte obrazy są
plikami dostarczonymi przez użytkownika; przed publicznym udostępnieniem projektu
warto sprawdzić ich źródła i licencje.

