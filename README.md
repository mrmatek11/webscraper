# snap.py

**Web Snapshot Tool** — narzędzie do robienia pełnych backupów stron internetowych.  
Zapisuje HTML + wszystkie zasoby (CSS, JS, obrazki, fonty) + screenshoty do ZIP-a.  
Gotowe do użycia przez webmasterów, do szybkiego backupu przed zmianami na stronie.

```
██████  ███▄    █  ▄▄▄       ██▓███
▒██    ▒  ██ ▀█   █ ▒████▄    ▓██░  ██▒
░ ▓██▄   ▓██  ▀█ ██▒▒██  ▀█▄  ▓██░ ██▓▒
  ▒   ██▒▓██▒  ▐▌██▒░██▄▄▄▄██ ▒██▄█▓▒ ▒
▒██████▒▒▒██░   ▓██░ ▓█   ▓██▒▒██▒ ░  ░
░  ▒▓▒ ▒ ░░ ▒░   ▒ ▒  ▒▒   ▓▒█░▒▓▒░ ░  ░
░ ░▒  ░ ░░ ░░   ░ ▒░  ▒   ▒▒ ░░▒ ░
░  ░  ░     ░   ░ ░   ░   ▒   ░░
      ░           ░       ░  ░
  [ web snapshot tool ]
```

---

## Funkcje

- **Full backup** — zapisuje kompletną stronę: HTML, CSS, JS, obrazki, fonty, screenshot
- **Screenshots only** — szybkie screenshoty całych stron (1440px wide)
- **Crawl mode** — automatycznie odkrywa wszystkie podstrony z sitemap.xml + linki wewnętrzne
- **Slider Revolution support** — obsługa SR7 i RevSlider 6 (wymusza renderowanie tła)
- **Lazy load bypass** — wymusza ładowanie obrazków leniwych (data-src, data-lazy, srcset)
- **Cookie consent** — automatycznie akceptuje cookie banery
- **Anti-popup** — zamyka overlaye, modale, newslettery
- **Auto retry** — ponawia nawigację przy timeoutach CDN
- **Logowanie** — zapisuje log do pliku obok wyników

## Tryby ZIP-a

Pliki ZIP są oznaczone prefiksem żeby łatwo odróżnić typ backupu:

| Prefix | Tryb | Zawartość |
|--------|------|-----------|
| `FULL_` | full | HTML + assets + screenshot każdej strony |
| `CRAWL_` | crawl | To samo co full, ale strony odkryte automatycznie |
| `SCREENSHOTS_` | screenshots | Same screenshoty (PNG) |

---

## Instalacja

### Wymagania

- Python 3.8+
- Chromium (instalowany automatycznie przez Playwright)

### Szybka instalacja

```bash
git clone https://github.com/twoj-user/snap.git
cd snap
bash install.sh
```

### Ręczna instalacja

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Użycie

### Interaktywnie

```bash
python3 snap.py
```

Uruchomi menu z wyborem trybu i source URL-i.

### CLI

```bash
# Full backup jednej strony
python3 snap.py https://example.com

# Full backup — output do custom folderu
python3 snap.py https://example.com -o ./backup

# Screenshots only
python3 snap.py https://example.com --mode screenshots

# Crawl — automatyczne odkrywanie stron
python3 snap.py https://example.com --mode crawl

# Crawl z limitem stron
python3 snap.py https://example.com --mode crawl --max-pages 30

# Z pliku z listą URL-i
python3 snap.py -f lista_stron.txt --mode full

# Full backup + agresywne zamykanie popupów
python3 snap.py https://example.com --mode clean-full

# Zachowaj foldery (nie usuwaj po spakowaniu)
python3 snap.py https://example.com --keep-folders
```

### Parametry

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `urls` | URL-e do zrobienia backupu | — |
| `-f, --file` | Plik z listą URL-i (jeden na linię, `#` to komentarz) | — |
| `-o, --output` | Folder na wyniki | `./results` |
| `--mode` | `full`, `screenshots`, `crawl`, `clean-full`, `clean-screenshots`, `clean-crawl` | `full` |
| `--max-pages` | Limit stron w crawl mode | `50` |
| `--keep-folders` | Nie usuwaj folderów po spakowaniu do ZIP | off |

---

## lista_stron.txt

Plik z URL-ami do przetworzenia — jeden URL na linię:

```
# Komentarze zaczynające się od # są ignorowane

https://example.com
https://example.com/o-nas
https://example.com/kontakt

# https://strona-wylaczona.pl
```

---

## Struktura wyników

### Full / Crawl mode

```
results/
├── FULL_2026-05-05_14-30-00_example.com.zip
│   ├── homepage/
│   │   ├── index.html
│   │   ├── screenshot_full.png
│   │   ├── meta.txt
│   │   └── assets/
│   │       ├── style.css
│   │       ├── logo.png
│   │       └── ...
│   └── kontakt/
│       ├── index.html
│       ├── screenshot_full.png
│       ├── meta.txt
│       └── assets/
└── snap_2026-05-05_14-30-00.log
```

### Screenshots mode

```
results/
├── SCREENSHOTS_2026-05-05_14-30-00_example.com.zip
│   ├── 2026-05-05_example.com.png
│   ├── 2026-05-05_example.com_kontakt.png
│   └── ...
└── snap_2026-05-05_14-30-00.log
```

---

## Co robi snap.py pod maską

1. Otwiera stronę w headless Chromium (1440×900)
2. Ustawia cookie consent (żeby nie wyskakiwały bannery)
3. Nawiguje z `wait_until='networkidle'` (z retry 2x)
4. Zamyka popupy, modale, cookie bannery
5. Scroluje stronę (do 30000px) żeby wymusić lazy load
6. Wymusza ładowanie obrazków leniwych (data-src, data-lazy-src, srcset)
7. Renderuje slidery (Flickity, Slider Revolution 6, Slider Revolution 7)
8. Klika przez wszystkie slajdy karuzel (agresywnie, 10x)
9. Wyłącza animacje CSS (AOS, WOW)
10. Czeka na załadowanie fontów
11. Zamienia blob URL-e na base64
12. Zapisuje HTML z przepisanymi ścieżkami do lokalnych assets
13. Przepisuje CSS (url(), @import) na lokalne ścieżki
14. Dohandlowuje brakujące assets przez requests
15. Robi full-page screenshot (max 15000px)
16. Pakuje wszystko do ZIP-a z DEFLATE

---

## Ograniczenia

- Strony z anti-bot protection (Cloudflare challenge, reCAPTCHA Enterprise) mogą nie działać
- Strony wymagające logowania — można ustawić cookie consent ale nie full auth
- Single Page Apps z dynamicznym routingiem — crawl mode może nie znaleźć wszystkich stron
- Infinite scroll z bardzo dużą ilością treści — scroll limit 30000px

## Wymagania systemowe

- Linux / macOS / Windows (WSL)
- Python 3.8+
- ~200MB RAM na stronę (Chromium headless)
- Chromium (~400MB na dysku)

## Licencja

MIT
