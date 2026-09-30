# snap.py — Web Snapshot Tool v4.1

**Narzędzie do robienia pełnych backupów stron internetowych.**
Zapisuje HTML + wszystkie zasoby (CSS, JS, obrazki, fonty) + screenshoty do ZIP-a.
Gotowe do użycia przez webmasterów — szybki backup przed zmianami na stronie klienta.

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
  [ web snapshot tool v4.1 ]
```

---

## Funkcje

- **Full backup** — zapisuje kompletną stronę: HTML, CSS, JS, obrazki, fonty, screenshot
- **Screenshots only** — szybkie screenshoty całych stron (domyślnie 1920×1080, jak monitor Full HD)
- **Crawl mode** — automatycznie odkrywa wszystkie podstrony z `sitemap.xml` + linki wewnętrzne
- **Slider Revolution support** — obsługa SR7 i RevSlider 6 (wymusza renderowanie tła)
- **Lazy load bypass** — wymusza ładowanie obrazków leniwych (`data-src`, `data-lazy`, `srcset`, `data-lazy-load-src`, `data-lazy-background-image`, `data-bg-image`)
- **Cookie consent** — automatycznie akceptuje cookie banery (wielojęzyczne: PL, EN, DE, FR, ES, IT i inne)
- **Anti-popup** — zamyka overlaye, modale, newslettery, themify popupy
- **Animation killer** — wyłącza animacje CSS, JS (AOS, WOW, GSAP, anime.js, Elementor, Divi, Beaver Builder, Pixfort) przez `add_init_script()` + `document.getAnimations().finish()`
- **IntersectionObserver hijack** — wymusza natychmiastowe wywołanie callbacków IO (scroll-triggered content)
- **Fullpage scroll defuse** — neutralizuje fullpage.js i Locomotive Scroll
- **Blob → base64** — konwertuje blob URL-e na base64 inline
- **Route blocking** — blokuje analytics/tracking requesty dla szybkości
- **Multi-threaded crawl** — osobny browser per wątek (thread-safe)
- **Auto retry** — ponawia nawigację przy timeoutach CDN
- **Logging** — zapisuje log do pliku obok wyników
- **Webwave support** — obsługa data-ww_rwd, cookiePopup i innych specyficznych elementów Webwave

## Tryby pracy

| Tryb | CLI flag | Opis |
|------|----------|------|
| **Full backup** | `--mode full` | HTML + assets + screenshot każdej strony |
| **Screenshots** | `--mode screenshots` | Same screenshoty (PNG) |
| **Crawl** | `--mode crawl` | Automatyczne odkrywanie stron (sitemap + linki wewnętrzne) |
| **Clean full** | `--mode clean-full` | Full backup + agresywne zamykanie popupów |
| **Clean screenshots** | `--mode clean-screenshots` | Screenshots + agresywne zamykanie popupów |
| **Clean crawl** | `--mode clean-crawl` | Crawl + agresywne zamykanie popupów |

## Prefixy ZIP

Pliki ZIP są oznaczone prefiksem dla łatwej identyfikacji:

| Prefix | Tryb | Zawartość |
|--------|------|-----------|
| `FULL_` | full / clean-full | HTML + assets + screenshot każdej strony |
| `CRAWL_` | crawl / clean-crawl | To samo co full, ale strony odkryte automatycznie |
| `SCREENSHOTS_` | screenshots / clean-screenshots | Same screenshoty (PNG) |

---

## Instalacja

### Wymagania

- Python 3.8+
- Chromium (instalowany automatycznie przez Playwright)

### Szybka instalacja

```bash
git clone https://github.com/mrmatek11/webscraper.git
cd webscraper
bash install.sh
```

### Ręczna instalacja

```bash
pip install -r requirements.txt
playwright install chromium
```

### Zależności

```
playwright>=1.40.0
requests>=2.28.0
```

---

## Użycie

### Interaktywnie (menu)

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

# Własny plik konfiguracyjny
python3 snap.py https://example.com -c /sciezka/do/snap.cfg
```

### Parametry CLI

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `urls` | URL-e do zrobienia backupu | — |
| `-f, --file` | Plik z listą URL-i (jeden na linię, `#` to komentarz) | — |
| `-o, --output` | Folder na wyniki | `./results` |
| `--mode` | `full`, `screenshots`, `crawl`, `clean-full`, `clean-screenshots`, `clean-crawl` | `full` |
| `--max-pages` | Limit stron w crawl mode | `50` (z snap.cfg) |
| `--keep-folders` | Nie usuwaj folderów po spakowaniu do ZIP | off |
| `-c, --config` | Ścieżka do pliku konfiguracyjnego snap.cfg | auto-detect |

---

## Konfiguracja (snap.cfg)

Plik `snap.cfg` w katalogu projektu pozwala dostosować parametry bez podawania ich w CLI:

```ini
[performance]
workers = 1              # Liczba wątków (crawl mode)
block_analytics = true  # Blokuj analytics/tracking requesty

[browser]
viewport_width = 1920        # Szerokość viewportu
viewport_height = 1080       # Wysokość viewportu
device_scale_factor = 1      # 1 = zwykły monitor, 1.25 = laptop Windows, 2 = Retina
max_screenshot_height = 15000  # Max wysokość screenshotu w px

[crawl]
max_pages = 50            # Domyślny limit stron do odkrycia
```

Program szuka `snap.cfg` w kolejności:
1. Ścieżka podana przez `-c` / `--config`
2. `./snap.cfg` (bieżący katalog)
3. `snap.cfg` obok `snap.py`

---

## Plik z listą URL-i

Format pliku (jeden URL na linię, `#` to komentarz):

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
├── FULL_2026-06-24_14-30-00_example.com.zip
│   ├── homepage/
│   │   ├── index.html
│   │   ├── screenshot_full.png
│   │   ├── meta.txt
│   │   └── assets/
│   │       ├── style.css
│   │       ├── script.js
│   │       ├── logo.png
│   │       └── font.woff2
│   └── kontakt/
│       ├── index.html
│       ├── screenshot_full.png
│       ├── meta.txt
│       └── assets/
└── snap_2026-06-24_14-30-00.log
```

### Screenshots mode

```
results/
├── SCREENSHOTS_2026-06-24_14-30-00_example.com.zip
│   ├── 2026-06-24_example.com.png
│   ├── 2026-06-24_example.com_o-nas.png
│   ├── 2026-06-24_example.com_kontakt.png
│   └── ...
└── snap_2026-06-24_14-30-00.log
```

### Crawl mode

```
results/
├── CRAWL_2026-06-24_14-30-00_example.com.zip
│   ├── crawl_pages/
│   │   ├── example.com/
│   │   │   ├── index.html
│   │   │   ├── screenshot_full.png
│   │   │   └── assets/
│   │   ├── example.com_o-nas/
│   │   │   ├── index.html
│   │   │   ├── screenshot_full.png
│   │   │   └── assets/
│   │   └── ...
│   └── urls_found.txt
└── snap_2026-06-24_14-30-00.log
```

---

## Co robi snap.py pod maską

1. Otwiera stronę w pełnym Chromium w trybie headless (1920x1080), z User-Agentem zgodnym z wersją przeglądarki
2. Wstrzykuje **init script** — globalny CSS killer animacji + IntersectionObserver hijack + localStorage consent flags
3. Ustawia cookie consent (żeby nie wyskakiwały bannery)
4. Nawiguje z `wait_until='networkidle'` (z retry 2x)
5. Zamyka popupy, modale, cookie bannery
6. Neutralizuje fullpage scroll (fullpage.js) i Locomotive Scroll
7. Scroluje stronę (do 30000px) żeby wymusić lazy load
8. Wymusza ładowanie obrazków leniwych (`data-src`, `data-lazy-src`, `srcset`, `data-lazy-load-src`, `data-lazy-background-image`, `data-bg-image`, `data-ww_rwd`)
9. Renderuje slidery (Slider Revolution 6, Slider Revolution 7)
10. Przeklikuje wszystkie slajdy karuzel (Slick, Webwave, Owl, Swiper — 10x)
11. Wyłącza animacje CSS (AOS, WOW, GSAP, anime.js, Elementor, Divi, Beaver Builder, Pixfort)
12. Wywołuje `document.getAnimations().finish()` + specyficzne finishery JS
13. Czeka na załadowanie obrazków (`naturalWidth > 0`, timeout 8s)
14. Czeka na załadowanie fontów
15. Konwertuje blob URL-e na base64
16. Zapisuje HTML z przepisanymi ścieżkami do lokalnych assets
17. Przepisuje CSS (`url()`, `@import`) na lokalne ścieżki
18. Dohandlowuje brakujące assets przez requests (w tym fonty z CSS)
19. Robi full-page screenshot (max 15000px)
20. Pakuje wszystko do ZIP-a z DEFLATE

---

## Co nowego w v4.1

| # | Zmiana |
|---|--------|
| A | `add_init_script()` przed nawigacją — globalny CSS killer animacji + IntersectionObserver hijack + localStorage consent flags. Zastępuje większość `_force_*_render` funkcji z v3. |
| B | Architektura: **jeden browser per wątek** (nie per run). v4.0 używał jednego browsera dla wszystkich wątków — Playwright sync API jest greenlet-bound i crashował przy `ThreadPoolExecutor`. v4.1: każdy wątek tworzy własny `playwright+browser` via `_thread_local`. |
| C | Rozszerzony lazy loader: `data-lazy-load-src`, `data-lazy-background-image`, `data-background-image`, `data-bg-image` + parsowanie `data-ww_rwd` (Webwave). |
| D | `_finish_all_animations`: `document.getAnimations().finish()` + GSAP + WOW + AOS + anime.js w jednej funkcji. |
| E | Lepszy cookie killer: Webwave `cookiePopup`, localStorage flags, "Allow All" button auto-click w wielu językach (PL, EN, DE, FR, ES, IT i inne). |
| F | `_wait_for_images`: sprawdza `naturalWidth > 0` (nie tylko `complete`). |
| G | Slider walkthrough: przeklikuje wszystkie dots dla Slick / Webwave / Owl / Swiper. |
| H | Route blocking: analytics/tracking blokowane dla szybkości. |
| I | Diagnostyka na końcu: zlicza puste/niewidoczne elementy → log. |
| J | `max_screenshot_height` przeniesione do `_CFG` (thread-safe). |

---

## Google Colab

Notebook [`snap_colab_optimized.ipynb`](snap_colab_optimized.ipynb) odpala `snap.py` w Colabie, bez instalowania czegokolwiek lokalnie.
Pobiera aktualny `snap.py` z GitHuba, więc poprawki w repo działają w nim od razu. Ma formularz z ustawieniami
(tryb, viewport, skala, etykieta `przed`/`po`) i opcję zapisu wyników na Google Drive.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/mrmatek11/webscraper/blob/main/snap_colab_optimized.ipynb)

## Ograniczenia

- Strony z **anti-bot protection** (Cloudflare challenge, reCAPTCHA Enterprise) mogą nie działać
- Strony wymagające **logowania** — można ustawić cookie consent ale nie pełną autoryzację
- **Single Page Apps** z dynamicznym routingiem — crawl mode może nie znaleźć wszystkich stron
- **Infinite scroll** z bardzo dużą ilością treści — scroll limit 30000px

## Wymagania systemowe

- Linux / macOS / Windows (WSL)
- Python 3.8+
- ~200MB RAM na stronę (Chromium headless)
- Chromium ~400MB na dysku

## Struktura repozytorium

```
webscraper/
├── snap.py            # Główny skrypt
├── snap.cfg           # Konfiguracja domyślna
├── install.sh         # Skrypt instalacyjny
├── requirements.txt   # Zależności Pythona
├── LICENSE            # Licencja MIT
└── README.md          # Ten plik
```

## Licencja

MIT — zobacz plik [LICENSE](LICENSE)
