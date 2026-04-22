Python CLI tool for archiving client websites — full-page screenshots + HTML/assets saved into dated ZIPs, grouped by domain. Powered by Playwright headless Chromium.

# snap.py — Web Snapshot Tool

Narzędzie do archiwizacji stron internetowych. Podajesz listę URL-i,
skrypt robi pełne screenshoty i/lub zapisuje HTML z assetami,
pakuje wszystko do ZIPa nazwanego datą i domeną klienta.

```
  ██████  ███▄    █  ▄▄▄       ██▓███
▒██    ▒  ██ ▀█   █ ▒████▄    ▓██░  ██▒
░ ▓██▄   ▓██  ▀█ ██▒▒██  ▀█▄  ▓██░ ██▓▒
  ▒   ██▒▓██▒  ▐▌██▒░██▄▄▄▄██ ▒██▄█▓▒ ▒
▒██████▒▒▒██░   ▓██░ ▓█   ▓██▒▒██▒ ░  ░
```

---

## Tryby działania

| Tryb | Co robi |
|------|---------|
| `full` | HTML + assety (CSS/JS/obrazki) + screenshot → ZIP per domena |
| `screenshots` | Same screenshoty → ZIP per domena |

---

## Wymagania systemowe

- Linux Mint 20+ (Ubuntu 20.04+)
- Python 3.8+
- pip

---

## Instalacja

### 1. Sprawdź czy masz Pythona

```bash
python3 --version
```

Powinno pokazać `Python 3.8.x` lub wyżej. Jeśli nie:

```bash
sudo apt update
sudo apt install python3 python3-pip -y
```

### 2. Zainstaluj zależności Pythona

```bash
pip install playwright requests
```

> Jeśli pip nie jest na PATH, użyj:
> ```bash
> python3 -m pip install playwright requests
> ```

### 3. Dodaj pip do PATH (jeśli dostajesz "command not found")

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 4. Zainstaluj przeglądarkę Chromium dla Playwright

```bash
playwright install chromium
```

Playwright pobiera własną wersję Chromium (~170 MB), niezależną od systemowej przeglądarki.

### 5. Zainstaluj zależności systemowe Chromium (jeśli coś nie działa)

```bash
playwright install-deps chromium
```

---

## Użycie

### Interaktywne menu (zalecane)

```bash
python3 snap.py
```

Skrypt zapyta o tryb, źródło URL-i i folder wyjściowy.

### Z flagami (do automatyzacji)

```bash
# Pełne archiwum z pliku
python3 snap.py -f lista_stron.txt --mode full

# Same screenshoty z pliku
python3 snap.py -f lista_stron.txt --mode screenshots

# Pojedynczy URL
python3 snap.py https://example.com --mode screenshots

# Własny folder wyjściowy
python3 snap.py -f lista_stron.txt -o ~/Desktop/archiwum --mode full
```

---

## Plik z URL-ami

Utwórz plik `lista_stron.txt`, jeden URL na linię.
Linie zaczynające się od `#` są ignorowane.

```
https://example.com
https://example.com/produkty/cokolwiek/
# ta strona jest wylaczona
https://innadomena.pl
```

---

## Struktura wyjściowa

### Tryb `full`

```
results/
└── 2026-04-21_14-30_ecomess.pl.zip
    └── ecomess.pl/
        ├── homepage/
        │   ├── index.html
        │   ├── screenshot_full.png
        │   ├── meta.txt
        │   └── assets/
        │       ├── style.css
        │       └── logo.png
        ├── produkty_picoflux-air/
        │   ├── index.html
        │   ├── screenshot_full.png
        │   └── assets/
        └── kategorie_odczyt-zdalny/
```

### Tryb `screenshots`

```
results/
└── 2026-04-21_14-30_ecomess.pl.zip
    ├── 2026-04-21_14-30_ecomess.pl.png
    ├── 2026-04-21_14-30_ecomess.pl_produkty_picoflux-air.png
    └── 2026-04-21_14-30_ecomess.pl_kategorie_odczyt-zdalny.png
```

Każdy run dostaje unikalną nazwę ZIPa z godziną — uruchamiając skrypt
wielokrotnie tego samego dnia nic się nie nadpisuje.

---

## Opcje

| Flaga | Opis | Domyślnie |
|-------|------|-----------|
| `-f`, `--file` | Plik TXT z URL-ami | — |
| `-o`, `--output` | Folder wyjściowy | `./results` |
| `--mode` | `full` lub `screenshots` | `full` |
| `--keep-folders` | Zachowaj foldery tymczasowe po spakowaniu | wyłączone |

---

## Rozwiązywanie problemów

**`playwright: command not found`**
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

**`playwright install chromium` pobiera bardzo wolno**
Normalka, plik ma ~170 MB. Wystarczy zrobić raz.

**Screenshot jest ucięty / strona się nie załadowała**
Niektóre strony blokują headless browsery. Skrypt próbuje fallbacku
na `domcontentloaded` jeśli `networkidle` przekroczy timeout.

**`ModuleNotFoundError: No module named 'playwright'`**
```bash
pip install playwright --break-system-packages
```

---

## Stack

- [Playwright](https://playwright.dev/python/) — headless Chromium, screenshoty, JS rendering
- [requests](https://docs.python-requests.org/) — pobieranie assetów
- Python 3.8+ stdlib — zipfile, pathlib, argparse
