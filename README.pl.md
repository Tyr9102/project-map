# Project Map

[![English](https://img.shields.io/badge/English-1f6feb?style=for-the-badge)](README.md) [![Polski](https://img.shields.io/badge/Polski-555555?style=for-the-badge)](README.pl.md)

[![tests](https://github.com/Tyr9102/project-map/actions/workflows/test.yml/badge.svg)](https://github.com/Tyr9102/project-map/actions/workflows/test.yml)

Pilnuj swojego projektu jednym spojrzeniem. Gdy projekt rośnie, trudno go ogarnąć z samej rozmowy w terminalu: co już działa, co jest w toku, gdzie czyhają pułapki. Project Map pokazuje całość jako mapę kafelków w przeglądarce, prostym językiem, bez kodu. A gdy chcesz coś zmienić, nie musisz długo opisywać w terminalu, o który fragment chodzi. Klikasz kafelek, piszesz uwagę dokładnie przy nim, a Claude wie, czego dotyczy. Mapa nie zastępuje pracy w terminalu - to dalej tam rozmawiasz z Claude'em i budujesz projekt. Pomaga trzymać kontekst w jednym miejscu i w trakcie pracy szybko doprecyzować konkretną kwestię.

Wtyczka do Claude Code, która zamienia rozmowę o projekcie w mapę kafelków w przeglądarce. Zostawiasz uwagi na kafelkach, klikasz **Wyślij**, a otwarta sesja Claude Code sama się budzi, odpowiada przy kafelkach i poprawia mapę.

![Uwaga wysłana z mapy budzi sesję Claude Code, która odpowiada i poprawia mapę](docs/demo.gif)

*Prawdziwe nagranie, przyspieszone w czasie pracy Claude'a: po lewej wysłanie uwagi, po prawej sesja budzi się w ciągu sekundy.*

Dla osób, które myślą o projekcie bez czytania kodu: to, co ważne, prostym językiem, w strefach czytanych z góry na dół - cel, jak to działa, funkcje, zasady i pułapki, pytania i pomysły.

## Co robi

- **„Zrób mapę projektu”** - Claude czyta dokumentację i historię projektu, sprawdza funkcje w kodzie i buduje mapę. Kafelki, których nie potwierdził, oznacza jako otwarte pytania.
- **Uwagi na kafelkach** - komentarz, pytanie albo sugestia. Zbierasz kilka szkiców i wysyłasz je jedną paczką.
- **Filtr jednym kliknięciem** - przyciski statusów z licznikami (działa, pułapka, otwarte pytanie...) przygaszają pozostałe kafelki. Na szerokim ekranie panel uwag stoi obok mapy, więc cały czas go widać.
- **Wyślij budzi sesję** - w 1-2 sekundy, bez pisania w terminalu. Odpowiedzi pojawiają się przy kafelkach.
- **Mapa nadąża** - po commicie Claude poprawia kafelki, a na starcie sesji zgłasza commity, których mapa jeszcze nie widziała. Decyzje z rozmowy trafiają na mapę od razu, a pomysły z burzy mózgów tylko te, które wybierzesz na jej koniec - żeby mapa nie zapełniła się każdym „a gdyby tak”.
- **Wszystko zostaje u Ciebie** - strona działa na `127.0.0.1`, mapy to zwykłe pliki JSON na dysku. Nic nie wychodzi nigdzie poza Claude'a, w ramach Twojej zwykłej sesji.

Strona mówi po polsku albo po angielsku, zależnie od języka przeglądarki.

## Wymagania

- [Claude Code](https://code.claude.com)
- Python 3.9 lub nowszy jako `python3` albo `python` (tylko biblioteka standardowa, nic do instalowania)
- git (do funkcji „mapa nadąża”)
- Na Windowsie: Git Bash, który przychodzi z Git for Windows

## Instalacja

W Claude Code:

```
/plugin marketplace add Tyr9102/project-map
/plugin install project-map@project-map
```

Potem zezwól na nasłuch - małe polecenie w tle, dzięki któremu **Wyślij** budzi sesję. Wpisz `/permissions` i dodaj regułę zezwalającą `Bash(project-map-watch:*)` albo wpisz ją do `~/.claude/settings.json`:

```json
{
  "permissions": { "allow": ["Bash(project-map-watch:*)"] }
}
```

Możesz też pominąć ten krok: przy pierwszej mapie Claude zapyta, czy dodać regułę za Ciebie, i wpisze ją dopiero po „tak”.

Bez niej tryb auto może zablokować nasłuch (uruchamia kod z wtyczki, nie z Twojego projektu). Mapa działa wtedy bez budzenia Claude'a - zamiast tego piszesz „sprawdź mapę”.

Potem w katalogu projektu powiedz Claude'owi: **„zrób mapę projektu”**. Poda Ci adres, domyślnie `http://127.0.0.1:8765`.

Co się zmieniło w każdej wersji: [CHANGELOG.md](CHANGELOG.md) (po angielsku).

## Ustawienia

Opcjonalne, w bloku `env` pliku `~/.claude/settings.json`, żeby hooki i polecenia uruchamiane przez Claude'a widziały te same wartości:

| Zmienna | Domyślnie | Znaczenie |
| --- | --- | --- |
| `PROJECT_MAP_DIR` | `~/.project-map` | Gdzie trzymane są mapy |
| `PROJECT_MAP_PORT` | `8765` | Lokalny port strony z mapą |

```json
{
  "env": { "PROJECT_MAP_DIR": "/home/ty/mapy", "PROJECT_MAP_PORT": "8790" }
}
```

**Historia i kopia zapasowa:** zrób z katalogu map repozytorium git (`git init` w środku), a Claude będzie tam commitował każdą zmianę mapy.

## Jak to działa

- Mały lokalny serwer (Python, biblioteka standardowa) wyświetla stronę i zapisuje uwagi jako pliki, jedna uwaga w jednym pliku. Wtyczka uruchamia go na starcie sesji w projekcie, który ma mapę. Celowo działa dalej po zamknięciu Claude Code: dodaj stronę do zakładek, a mapy masz jedno kliknięcie od siebie, z sesją albo bez. Zatrzymuje się po restarcie komputera albo gdy powiesz Claude'owi **„zatrzymaj serwer mapy”**; następna sesja w projekcie z mapą uruchamia go ponownie.
- Nasłuch działa jako zadanie w tle Claude Code. Wyślij zapisuje plik z sygnałem; nasłuch go widzi, wypisuje i się kończy - a koniec zadania w tle to właśnie to, co budzi sesję. Claude uruchamia wtedy nowy nasłuch.
- Hook przy każdej wiadomości sprawdza, czy nasłuch tej sesji żyje, i prosi Claude'a o uruchomienie nowego, gdy nie żyje.
- Serwer odrzuca zmiany przychodzące z innych stron otwartych w przeglądarce.

## Bezpieczeństwo

- **Strony otwarte w przeglądarce nie mają dostępu do Twoich map.** Serwer odpowiada tylko pod lokalnym adresem, przyjmuje zmiany wyłącznie od samej strony z mapą odrzuca rodzaje zapytań, które obca strona mogłaby wysłać bez pytania, i nie pozwala innej stronie osadzić mapy w ramce.
- **Inne konta na tym samym komputerze nie otworzą plików Twoich map** - serwer zamyka katalog map tylko dla Ciebie (na Linuksie i macOS). **Mogą za to korzystać z serwera:** działa na Twoim koncie i odpowiada każdemu programowi na tym komputerze, więc inne konto przeczyta przez `127.0.0.1` Twoje mapy i uwagi, wyśle uwagę, usunie mapę i zatrzyma serwer. Zatrzymałoby to dopiero hasło w adresie strony, co przy tak rzadkim układzie się nie opłaca - na komputerze dzielonym z osobami, którym nie ufasz, nie trzymaj na mapie niczego poufnego.
- **Programy działające na Twoim koncie są zaufane**, jak przy każdym pliku na dysku: mogłyby wpisać uwagę prosto do katalogu map, z pominięciem serwera. Hasło na stronie niczego by tu nie zmieniło.

## Ograniczenia - przeczytaj, zanim zaczniesz na tym polegać

- **Opiera się na zachowaniu Claude Code, a nie na udokumentowanym API:** sesja budzi się, bo zakończone zadanie w tle zaczyna nową turę. Aktualizacja Claude Code może to zmienić.
- **Nasłuch żyje najwyżej 2 godziny** (limit Claude Code dla zadania w tle). Następna wiadomość, którą napiszesz, uruchamia nowy.
- **Każde obudzenie kosztuje tokeny** - to pełna tura z całym kontekstem sesji. Wysyłaj uwagi paczkami i otwieraj mapę w świeżej sesji.
- **Każdy commit w projekcie z mapą też kosztuje tokeny** - zaraz po nim, w tej samej turze, Claude czyta, co się zmieniło, poprawia kafelki, których zmiana dotyczy, i commituje mapę (do własnego repozytorium katalogu map, jeśli je ma). Zmiana, której mapa nie pokazuje, kosztuje tylko krótkie sprawdzenie.
- **Na co dzień używana tylko na Linuksie.** Testy automatyczne przechodzą na Linuksie, macOS i Windowsie, ale nikt jeszcze nie używał jej na macOS ani Windowsie.
- Po aktualizacji wtyczki już działający serwer trzyma starą wersję, dopóki go nie zatrzymasz - powiedz Claude'owi **„zatrzymaj serwer mapy”**. Następna sesja Claude Code uruchomi nową.

## Odinstalowanie

Najpierw powiedz Claude'owi **„zatrzymaj serwer mapy”**, potem:

```
/plugin uninstall project-map@project-map
```

Mapy zostają w `~/.project-map` (albo w Twoim `PROJECT_MAP_DIR`) - usuń ten katalog ręcznie, jeśli już ich nie potrzebujesz. Usuń też regułę `Bash(project-map-watch:*)`, jeśli była dodana.

## Rozwój

```
python3 tests/run_tests.py        # testy hooka, nasłuchu i serwera, na tymczasowych mapach i wolnym porcie
claude --plugin-dir .             # Claude Code z wtyczką z tego katalogu
```

## Licencja

MIT
