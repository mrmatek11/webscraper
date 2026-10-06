#!/usr/bin/env bash
# Instalator snap.py dla Linux Mint 20/21/22 (i Ubuntu 20.04+).
# Uruchom w folderze projektu:  bash install.sh
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

echo ""
echo "  snap.py — instalator"
echo "  ────────────────────"
echo "  (za chwilę system może zapytać o hasło — to hasło do Twojego konta)"
echo ""

echo "  [1/5] Pakiety systemowe (Python, venv)..."
# błędy obcych repozytoriów (np. wygasły klucz Spotify/Chrome) nie mogą przerwać instalacji
$SUDO apt-get update -qq || true
$SUDO apt-get install -y -qq python3 python3-venv python3-pip > /dev/null

echo "  [2/5] Środowisko Pythona (.venv) + biblioteki..."
python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

# Mint 20 / Ubuntu 20.04 (focal): Playwright >= 1.63 nie ma już Chromium dla tego systemu
. /etc/os-release 2>/dev/null || true
if [ "${UBUNTU_CODENAME:-$VERSION_CODENAME}" = "focal" ]; then
    echo "        (system na bazie Ubuntu 20.04 — instaluję Playwright < 1.63)"
    .venv/bin/python -m pip install --quiet "playwright<1.63"
fi

echo "  [3/5] Przeglądarka Chromium (~150 MB)..."
$SUDO .venv/bin/python -m playwright install-deps chromium > /dev/null
.venv/bin/python -m playwright install chromium

echo "  [4/5] Fonty jak na Windowsie (Arial, Verdana...) + emoji..."
$SUDO apt-get install -y -qq fonts-liberation fonts-noto-color-emoji > /dev/null 2>&1 || true
# Fonty Microsoftu pobierają się z internetu przy instalacji pakietu. Jeśli się
# nie uda, usuwamy pakiet — inaczej zostaje w połowie i blokuje apt.
echo "ttf-mscorefonts-installer msttcorefonts/accept-mscorefonts-eula select true" | $SUDO debconf-set-selections
if ! $SUDO apt-get install -y -qq ttf-mscorefonts-installer > /dev/null 2>&1; then
    $SUDO apt-get remove --purge -y -qq ttf-mscorefonts-installer > /dev/null 2>&1 || true
    echo "        (fonty Microsoftu się nie zainstalowały — to nie przeszkadza w działaniu)"
fi

echo "  [5/5] Skrót startowy..."
chmod +x snap.sh

echo ""
echo "  ✅ Gotowe!"
echo ""
echo "  Uruchamianie:"
echo "    ./snap.sh                                          (menu z pytaniami)"
echo "    ./snap.sh https://example.com --mode screenshots"
echo "    ./snap.sh -f lista_stron.txt --mode screenshots"
echo ""
echo "  Wyniki (pliki ZIP) lądują w folderze: $DIR/results"
echo ""
