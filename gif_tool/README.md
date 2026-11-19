# GIF 160×128 • Pixel Tool

Desktopowa aplikacja Windows do przygotowywania obrazów i animacji dla ekranu
160×128. Plik można przeciągnąć do okna albo wskazać po kliknięciu.

- **Skaluj do GIF** – centralnie kadruje do proporcji 5:4 i zapisuje GIF 160×128.
- **Zrób Pixel Art** – dodatkowo redukuje rozdzielczość i kolory zgodnie z
  wybranym stylem oraz paletą.
- Animowane GIF-y zachowują liczbę klatek, czasy klatek i ustawienie pętli.
- Orientacja EXIF ze zdjęć wykonanych telefonem lub aparatem jest automatycznie
  wykrywana i korygowana przed kadrowaniem.
- Wyniki trafiają do folderu, w którym znajduje się program. Istniejące pliki
  nie są nadpisywane; kolejna wersja otrzymuje numer.

## Budowanie EXE

Uruchom `build.bat`. Skrypt tworzy lokalne środowisko, instaluje Pillow,
tkinterdnd2 i PyInstaller, a potem buduje `GIF-160x128.exe`.
