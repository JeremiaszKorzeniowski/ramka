# Ramka — ESP8266 + ST7735

ESP8266 odtwarza obrazy i animacje GIF zapisane na karcie microSD. Ekran pracuje
poziomo w rozdzielczości 160×128, a plik zmienia się co 12 sekund. Wbudowany
panel WWW umożliwia wgrywanie, pobieranie i usuwanie GIF-ów bez wyjmowania karty.

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

Obrót wybiera poprzednią lub następną animację. Krótkie naciśnięcie przełącza
tryb automatyczny i stały. Przytrzymanie przez 3 sekundy otwiera menu biblioteki,
w którym można wybrać źródło, tag, kolejność oraz konkretny plik.

`D3` jest pinem startowym ESP8266. Nie trzymaj wciśniętego enkodera podczas
włączania zasilania ani resetowania płytki, bo ESP8266 może wejść w tryb programowania.
Jeśli jest to goły enkoder bez płytki i rezystorów, linia podłączona do D0 może
wymagać zewnętrznego rezystora podciągającego 10 kΩ do 3,3 V.

## Uruchomienie

1. Otwórz `ramka.ino` w Arduino IDE albo katalog projektu w VS Code z PlatformIO.
2. Włóż kartę microSD sformatowaną jako FAT32 (na początek najlepiej 4–32 GB).
3. W Arduino IDE wybierz `NodeMCU 1.0 (ESP-12E Module)` i właściwy port COM.
4. Zainstaluj biblioteki `Adafruit GFX Library`, `Adafruit ST7735 and ST7789
   Library`, `AnimatedGIF` autorstwa Larry Bank oraz `WiFiManager` autorstwa
   tzapu.
5. Zbuduj i wgraj szkic.

## Pierwsze połączenie z Wi-Fi

1. Po uruchomieniu ramka próbuje połączyć się z ostatnio zapisaną siecią.
2. Przy pierwszym uruchomieniu tworzy punkt dostępowy `RAMKA-SETUP` z hasłem
   `ramka123`.
3. Połącz telefon lub komputer z tą siecią. Portal konfiguracji powinien otworzyć
   się automatycznie; jeśli nie, wejdź na `http://192.168.4.1`.
4. Wybierz domową sieć Wi-Fi i wpisz jej hasło.
5. Po połączeniu otwórz `http://ramka.local`. Jeśli nazwa lokalna nie działa,
   użyj adresu IP pokazanego na ekranie lub w Monitorze portu szeregowego.

Portal konfiguracyjny czeka trzy minuty. Po przekroczeniu tego czasu urządzenie
przechodzi w tryb offline i nadal wyświetla pliki z karty; reset uruchamia kolejną
próbę połączenia.

## Panel WWW

Panel `ramka.local` pozwala:

- zobaczyć wszystkie pliki `.gif` w katalogu głównym i podfolderach;
- wgrać GIF z komputera lub telefonu;
- pobrać GIF z bezpośredniego adresu `http://` albo `https://`;
- usunąć wybrany plik;
- skasować zapisane dane Wi-Fi i ponownie uruchomić konfigurację.

Program GIF 160×128 korzysta dodatkowo z API ramki:

- `POST /upload` wgrywa plik i zastępuje istniejący plik o tej samej nazwie;
  parametr `folder` pozwala wysłać go do jednego poziomu podfolderu;
- `GET /api/files` zwraca listę GIF-ów i ich rozmiary w formacie JSON;
- `GET /file?name=obraz.gif` pobiera wskazany GIF z karty SD.

Nazwy plików mogą zawierać litery ASCII, cyfry, kropkę, myślnik i podkreślenie.
Pobierany plik może mieć maksymalnie 6 MB, a sam obraz nie może przekraczać
160×128 pikseli. Panel nie ma logowania, dlatego powinien działać wyłącznie w
zaufanej sieci domowej.

## Gdy ekran wygląda źle

- biały ekran: sprawdź zasilanie, CS, DC, RST, SCK i MOSI;
- przesunięte kolory/obraz: zamień `INITR_BLACKTAB` w `ramka.ino` na
  `INITR_GREENTAB` albo `INITR_REDTAB`;
- obraz obrócony: zmień `tft.setRotation(1)` na wartość 0, 2 lub 3;
- odwrócone kolory: po `initR` dodaj `tft.invertDisplay(true)`.

## Pliki

Program automatycznie wykrywa do 64 plików `.gif` w katalogu głównym oraz w jednym
poziomie podfolderów. Obsługuje do 12 folderów i 24 tagów. Źródło `Wszystkie`
łączy całą bibliotekę, a `Główny` oznacza pliki leżące bezpośrednio na karcie.

Tagi zapisuje się po podwójnym podkreśleniu i rozdziela pojedynczym `_`, np.
`kicia__kot_smieszne_pixel.gif`. Na ekranie wyświetlana jest nazwa `kicia`, a tagi
są dostępne jako filtry. Kolejność może być alfabetyczna albo losowa bez powtórek
do czasu przejścia przez całą aktywną listę.

Użyte obrazy są plikami dostarczonymi przez użytkownika;
przed publicznym udostępnieniem projektu warto sprawdzić ich źródła i licencje.

