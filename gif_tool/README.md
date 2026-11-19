# GIF 160×128 • Pixel Tool

Desktopowa aplikacja Windows do przygotowywania obrazów i animacji dla ekranu
160×128. Pliki można przeciągnąć do okna albo wskazać po kliknięciu.
Można zaznaczyć lub przeciągnąć wiele plików naraz; wszystkie zostaną
przetworzone tym samym stylem i ustawieniami, a błąd jednego pliku nie zatrzyma
pozostałych.

- **Skaluj do GIF** – kadruje zaznaczony obszar do proporcji 5:4 i zapisuje
  GIF 160×128.
- Podgląd pokazuje żółtą ramkę kadru 5:4 z czerwonymi uchwytami.
  Ramkę można przesuwać myszą, a jej rozmiar zmieniać kółkiem lub
  przyciskami **−** i **+**. Oddalenie może wyjść poza zdjęcie; brakujący
  obszar zostanie wypełniony czarnym tłem. **Całość** od razu pokazuje cały
  obraz w formacie 5:4, a **Reset** przywraca kadr domyślny.
- Przy wielu plikach strzałki pod podglądem pozwalają ustawić osobny kadr
  dla każdego obrazu. W animowanym GIF-ie wybrany kadr jest stosowany do
  wszystkich klatek.
- **Zrób Pixel Art** – dodatkowo redukuje rozdzielczość i kolory zgodnie z
  wybranym stylem oraz paletą.
- **Manga czarno-biała** – zamienia zdjęcie lub animację w czarno-biały rysunek z
  wyraźnym konturem i rastrem drukarskim, charakterystycznym dla mangi.
- **Anime malarskie** – nadaje obrazowi cieplejszą, pastelową paletę, wygładza
  fotograficzny szum i dodaje delikatne brązowo-grafitowe linie tylko na mocnych
  krawędziach. Efekt nawiązuje do klasycznej, ręcznie malowanej animacji.
- Animowane GIF-y zachowują liczbę klatek i czasy klatek oraz zawsze otrzymują
  nieskończoną pętlę.
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
- Pole **Folder na karcie** zapisuje wyniki w podfolderze o bezpiecznej nazwie.
- Pole **Tagi** przyjmuje słowa rozdzielone przecinkami lub spacjami. Tagi są
  normalizowane i dopisywane do nazwy po `__`, np.
  `kicia-standard-160x128__kot_smieszne.gif`.
- Każdy gotowy GIF jest również kopiowany do `wyslij do ramki`. Przycisk
  **Wyślij do ramki** przesyła wszystkie GIF-y wraz ze strukturą jednego poziomu
  folderów na kartę SD; pliki o tej samej nazwie są zastępowane.
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
