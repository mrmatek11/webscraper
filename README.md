# 📸 snap.py — screenshoty i backupy stron

Robi **screenshot całej strony** (od góry do dołu) i/lub **pełną kopię strony** (HTML, obrazki, style, fonty).
Wszystko pakuje do pliku ZIP.

Do czego to jest: **przed** zmianami na stronie klienta robisz backup, **po** zmianach robisz drugi i porównujesz.

---

## 🟢 Sposób 1: Google Colab (najprostszy, nic nie instalujesz)

Potrzebujesz tylko przeglądarki i konta Google.

### Krok 1: Otwórz notebook

Kliknij ten przycisk:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/mrmatek11/webscraper/blob/main/snap_colab_optimized.ipynb)

Otworzy się strona z kilkoma szarymi blokami (to są „komórki”).
Każdą komórkę uruchamiasz, klikając **▶ (trójkąt)** po jej lewej stronie.

> Jeśli wyskoczy okienko „Ten notatnik nie został utworzony przez Google”, kliknij **Uruchom mimo to**.

### Krok 2: Instalacja

Kliknij ▶ przy komórce **„1. Instalacja”**.
Poczekaj ok. 1–2 minuty, aż pojawi się ✅.

### Krok 3: Pobierz skrypt

Kliknij ▶ przy komórce **„2. Pobierz snap.py”**.
Niczego tu nie zmieniaj, zostaw `main`.

### Krok 4: Wpisz strony i ustawienia

W komórce **„3. Ustawienia i start”**:

1. Między `"""` a `"""` wklej adresy stron, **każdy w nowej linii**:
   ```
   URL_LIST = """
   https://tono.com.pl
   https://tono.com.pl/kontakt
   """
   ```
   Linię możesz wyłączyć, dopisując `#` na początku.

2. Z listy **MODE** wybierz, co ma zrobić:

   | Wybierz | Kiedy |
   |---|---|
   | `screenshots` | Chcesz tylko screeny (najszybsze). **Do „przed i po” to wystarczy.** |
   | `full` | Chcesz screen + pełną kopię strony (HTML, obrazki itd.). |
   | `crawl` | Podajesz tylko stronę główną, a skrypt sam znajdzie wszystkie podstrony. |
   | `clean-...` | To samo co wyżej, ale mocniej zamyka popupy i cookies. Użyj, gdy na screenie wisi jakiś baner. |

3. W polu **LABEL** wpisz `przed` albo `po`. Pliki trafią do osobnych folderów.

4. Resztę zostaw. (VIEWPORT `1920x1080` + SCALE `1` = zwykły monitor Full HD.)

5. Kliknij ▶. Zobaczysz postęp `[1/5] ... [2/5] ...`. Poczekaj, aż pojawi się `done`.

### Krok 5: Pobierz wyniki

Kliknij ▶ przy komórce **„4. Wyniki”**. Przeglądarka pobierze pliki ZIP.

> Jeśli przeglądarka zapyta „Zezwolić na pobieranie wielu plików?”, kliknij **Zezwól**.
> Chcesz, żeby pliki trafiły od razu na Google Drive? Zaznacz ☑ `COPY_TO_DRIVE` przed kliknięciem ▶.

### Robienie „przed i po”

1. Przed zmianami: przejdź kroki 1–5 z `LABEL = przed`.
2. Wprowadź zmiany na stronie.
3. Po zmianach: w kroku 4 zmień na `LABEL = po`, kliknij ▶, potem krok 5.
   (Kroków 1–3 nie trzeba powtarzać, jeśli karta Colaba jest nadal otwarta.)

---

## 🐧 Sposób 2: Linux Mint (20, 21, 22) / Ubuntu

### Instalacja (tylko raz)

**1. Otwórz terminal**: `Ctrl + Alt + T` (albo Menu → Terminal).

**2. Skopiuj i wklej to** (w terminalu wklejasz przez `Ctrl + Shift + V`), potem Enter:

```bash
command -v git > /dev/null || sudo apt install -y git; (git -C ~/webscraper pull 2>/dev/null || git clone https://github.com/mrmatek11/webscraper.git ~/webscraper) && cd ~/webscraper && bash install.sh
```

- Zapyta o **hasło**: wpisz hasło do swojego konta i Enter. **Podczas wpisywania nic się nie wyświetla, to normalne.**
- Instalacja trwa ok. 2–5 minut. Na końcu pojawi się **✅ Gotowe!**
- Program jest w folderze **`webscraper`** w Twoim katalogu domowym.

### Uruchamianie

**Opcja A: klikanie (najprościej)**

1. Otwórz folder `webscraper` w menedżerze plików.
2. Kliknij dwa razy **`snap.sh`** i wybierz **„Uruchom w terminalu”**.
3. Odpowiadaj na pytania, wpisując numer i Enter:
   - tryb: `2` = same screeny, `1` = pełny backup, `3` = crawl (sam szuka podstron), `4` = to samo z mocniejszym zamykaniem popupów
   - skąd adresy: `1` = z pliku `lista_stron.txt` (potem jeszcze raz Enter), `2` = wpisujesz ręcznie (po ostatnim adresie wciśnij Enter na pustej linii)
   - folder wyników: po prostu Enter
4. Wyniki (ZIP) są w folderze **`webscraper/results`**.

> Jeśli po dwukliku otwiera się edytor tekstu zamiast pytania: kliknij `snap.sh` prawym → **Właściwości → Uprawnienia** → zaznacz ☑ **„Zezwól na uruchamianie pliku jako programu”**.

**Opcja B: z terminala**

```bash
cd ~/webscraper

# jedna strona, same screeny
./snap.sh https://tono.com.pl --mode screenshots

# wiele stron z pliku (otwórz lista_stron.txt, wpisz adresy, każdy w nowej linii)
./snap.sh -f lista_stron.txt --mode screenshots

# cała strona ze wszystkimi podstronami
./snap.sh https://tono.com.pl --mode crawl
```

### Aktualizacja do najnowszej wersji

```bash
cd ~/webscraper && git pull
```

(Jeśli zmienił się plik `requirements.txt`, uruchom jeszcze raz `bash install.sh`.)

### Windows / Mac

Użyj Google Colab (Sposób 1). Alternatywa: zainstaluj Pythona z python.org (na Windowsie zaznacz ☑ „Add Python to PATH”),
a potem w folderze projektu: `pip install -r requirements.txt`, `python -m playwright install chromium`, `python snap.py`.

---

## 📦 Co jest w ZIP-ie

| Plik zaczyna się od | Zawartość |
|---|---|
| `SCREENSHOTS_...zip` | Same screeny PNG, jeden na podstronę |
| `FULL_...zip` | Folder na każdą podstronę: `index.html` (kopia strony), `screenshot_full.png`, `assets/` (obrazki, CSS, fonty) |
| `CRAWL_...zip` | To samo co FULL, ale dla wszystkich znalezionych podstron |

Kopię strony otwierasz, klikając dwa razy `index.html` w rozpakowanym folderze.

---

## ❓ Coś nie działa

| Problem | Co zrobić |
|---|---|
| Na screenie wisi baner cookies / popup | Użyj trybu `clean-screenshots` albo `clean-full` |
| Screen jest ucięty na dole | Zwiększ `MAX_SCREENSHOT_HEIGHT` (Colab) albo `max_screenshot_height` w `snap.cfg` |
| Colab: `ModuleNotFoundError` / „No module named snap” | Uruchom ponownie kroki 1 i 2 |
| Linux: `./snap.sh: Brak uprawnień` / `Permission denied` | Wpisz `chmod +x ~/webscraper/snap.sh` |
| Linux: „Brak instalacji — najpierw uruchom install.sh” | `cd ~/webscraper && bash install.sh` |
| Linux: błąd przy `apt` / „Could not get lock” | Instalator sam czeka do 2 min, a potem wypisze, jaki proces blokuje apt i co wpisać |
| Linux: `Playwright does not support chromium on ubuntu20.04` | Mint 20: zrób `cd ~/webscraper && git pull && bash install.sh` (nowy instalator sam dobiera wersję) |
| Linux: ostrzeżenia `NO_PUBKEY` / `GPG error` (np. Spotify) przy instalacji | Nie dotyczą snap.py, można je zignorować |
| Colab się zawiesza / „Your session crashed” | Zmniejsz `WORKERS` do 1–2 |
| Brakuje jakiegoś elementu na screenie | Zapisz adres strony i zgłoś, a my to poprawimy |
| Strona w ogóle się nie otwiera (Cloudflare, logowanie) | Tego narzędzie nie obejdzie |

---

## ⚙️ Dla zaawansowanych

### Plik `snap.cfg`

```ini
[performance]
workers = 3              # ile stron naraz (4 GB RAM → 1, 8 GB → 2-3, 16 GB → 4-6)

[browser]
viewport_width  = 1920   # rozdzielczość okna przeglądarki
viewport_height = 1080
device_scale_factor = 1  # 1 = zwykły monitor, 1.25 = laptop Windows, 2 = Retina (plik 4x większy)
max_screenshot_height = 30000

[crawl]
max_pages = 9999         # limit podstron w trybie crawl
```

### Wszystkie opcje CLI

| Opcja | Opis | Domyślnie |
|---|---|---|
| `urls` | adresy stron | — |
| `-f, --file` | plik z listą adresów (`#` = komentarz) | — |
| `-o, --output` | folder na wyniki | `./results` |
| `--mode` | `full`, `screenshots`, `crawl`, `clean-full`, `clean-screenshots`, `clean-crawl` | `full` |
| `--max-pages` | limit podstron w crawl | z `snap.cfg` |
| `--keep-folders` | nie usuwaj folderów po spakowaniu | wyłączone |
| `--config` | inny plik konfiguracyjny | `snap.cfg` |

### Co skrypt robi z każdą stroną

1. Otwiera ją w pełnym Chromium (1920×1080, User-Agent zwykłego Chrome na Windows).
2. Akceptuje/zamyka cookies i popupy (wiele języków, Cookiebot, OneTrust, Webwave i inne).
3. Wyłącza animacje, preloadery, fullpage.js, Locomotive Scroll i Pixfort.
4. Przewija stronę, żeby załadować leniwe obrazki (lazy load, Webwave `data-ww_rwd`).
5. Renderuje slidery (Slider Revolution, Swiper, Slick, Owl).
6. Czeka na obrazki i fonty.
7. (tryb full) Zapisuje HTML i wszystkie zasoby z podmienionymi ścieżkami na lokalne.
8. Zdejmuje blokady scrolla i rozwija wewnętrzne kontenery, żeby screen objął całą stronę.
9. Robi screenshot całej strony i pakuje wszystko do ZIP.

### Pliki w repo

```
snap.py                     # główny skrypt
snap.cfg                    # ustawienia
snap_colab_optimized.ipynb  # wersja do Google Colab
lista_stron.txt             # przykładowa lista adresów
requirements.txt            # biblioteki Pythona
install.sh                  # instalator (Linux Mint / Ubuntu)
snap.sh                     # uruchamianie na Linuksie (po install.sh)
```

### Ograniczenia

- Strony z ochroną anty-bot (Cloudflare challenge, reCAPTCHA) mogą nie działać.
- Strony za logowaniem: nie.
- Aplikacje SPA: crawl może nie znaleźć wszystkich podstron.
