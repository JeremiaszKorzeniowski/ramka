# GIF 160×128 • Pixel Tool

Desktopowa aplikacja Windows do przygotowywania obrazów i animacji dla ekranu
160×128. Pliki można przeciągnąć do okna albo wskazać po kliknięciu.
Można zaznaczyć lub przeciągnąć wiele plików naraz; wszystkie zostaną
przetworzone tym samym stylem i ustawieniami, a błąd jednego pliku nie zatrzyma
pozostałych.

- **Skaluj do GIF** – centralnie kadruje do proporcji 5:4 i zapisuje GIF 160×128.
- **Zrób Pixel Art** – dodatkowo redukuje rozdzielczość i kolory zgodnie z
  wybranym stylem oraz paletą.
- **Manga czarno-biała** – zamienia zdjęcie lub animację w czarno-biały rysunek z
  wyraźnym konturem i rastrem drukarskim, charakterystycznym dla mangi.
- **Kolorowe Anime** – upraszcza kolory do płaskich, nasyconych tonów i dodaje
  ciemny kontur w stylu animacji cel-shading.
- Animowane GIF-y zachowują liczbę klatek, czasy klatek i ustawienie pętli.
- Orientacja EXIF ze zdjęć wykonanych telefonem lub aparatem jest automatycznie
  wykrywana i korygowana przed kadrowaniem.
- GIF-y 160×128 trafiają do podfolderu `wyniki`. Pełnowymiarowe wersje
  stylizowane, zapisane przed skalowaniem, trafiają do `wyniki/duze_wersje`.
- Nazwa każdego pliku zawiera użyty efekt (`pixelart`, `manga`, `anime` albo
  `standard`). Istniejące pliki nie są nadpisywane; kolejna wersja otrzymuje numer.
- Lista **Kompresja GIF** pozwala wybrać docelowy limit 250 KB, 100 KB albo
  25 KB. Program używa wspólnej palety kolorów, łączy identyczne klatki i w
  razie potrzeby stopniowo ogranicza kolory oraz liczbę klatek. Łączny czas
  animacji pozostaje bez zmian.
- Po konwersji program pokazuje rzeczywisty rozmiar zapisanego GIF-a.
- Każdy gotowy GIF jest również kopiowany do `wyslij do ramki`. Przycisk
  **Wyślij do ramki** przesyła wszystkie GIF-y z tego folderu na kartę SD;
  pliki o tej samej nazwie są zastępowane.
- Przycisk **Pobierz z ramki** zapisuje wszystkie GIF-y z karty w folderze
  `obrazy w ramce`, również zastępując lokalne pliki o tych samych nazwach.
- Domyślny adres to `http://ramka.local`; można go zmienić w oknie programu.
  Funkcje transferu wymagają aktualnego firmware ramki z endpointami
  `/api/files` i `/file`.

## Dodawanie kolejnych stylów

Style są zdefiniowane w rejestrze `CONVERSION_STYLES` w `converter.py`.
Nowy wpis określa nazwę pliku, etykietę i kolor przycisku oraz funkcje
stylizacji i finalizacji. Interfejs tworzy przyciski z rejestru automatycznie.

## Budowanie EXE

Uruchom `build.bat`. Skrypt tworzy lokalne środowisko, instaluje Pillow,
tkinterdnd2 i PyInstaller, a potem buduje `GIF-160x128.exe`.
