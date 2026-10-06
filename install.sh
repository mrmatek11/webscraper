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

# Czeka, aż apt będzie wolny (Menedżer aktualizacji, automatyczne aktualizacje
# albo zawieszona poprzednia instalacja). Po 2 minutach mówi, co zrobić.
wait_for_apt() {
    command -v fuser > /dev/null || return 0
    local i pids
    for i in $(seq 1 60); do
        pids=$($SUDO fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock 2>/dev/null | xargs || true)
        [ -z "$pids" ] && return 0
        [ "$i" -eq 1 ] && echo "        (apt jest zajęty przez inny proces — czekam do 2 minut...)"
        sleep 2
    done
    echo ""
    echo "  ❌ apt (instalator pakietów) jest zajęty przez:"
    ps -o pid=,args= -p "$(echo $pids | tr ' ' ',')" 2>/dev/null | sed 's/^/       /'
    echo ""
    echo "  • Jeśli to Menedżer aktualizacji — poczekaj, aż skończy, albo go zamknij."
    echo "  • Jeśli to zawieszona poprzednia instalacja (np. ttf-mscorefonts-installer), wpisz:"
    echo "        sudo kill $pids"
    echo "        sudo dpkg --purge --force-remove-reinstreq ttf-mscorefonts-installer"
    echo "        sudo dpkg --configure -a"
    echo "    i uruchom ponownie:  bash install.sh"
    exit 1
}

echo ""
echo "  snap.py — instalator"
echo "  ────────────────────"
echo "  (za chwilę system może zapytać o hasło — to hasło do Twojego konta)"
echo ""

# Sprzątanie po starszych wersjach instalatora: pakiet z fontami Microsoftu
# pobiera je z SourceForge w trakcie instalacji i potrafi zawisnąć na zawsze,
# a niedokończony blokuje apt (każde kolejne apt-get próbuje go dokończyć).
cleanup_msfonts() {
    if dpkg -s ttf-mscorefonts-installer > /dev/null 2>&1 && \
       ! dpkg -s ttf-mscorefonts-installer 2>/dev/null | grep -q "^Status: install ok installed"; then
        echo "        (sprzątam niedokończoną instalację fontów Microsoftu...)"
        $SUDO pkill -f "[u]pdate-ms-fonts|[m]sttcorefonts|[p]ackage-data-downloader" 2>/dev/null || true
        sleep 3
        $SUDO dpkg --purge --force-remove-reinstreq ttf-mscorefonts-installer > /dev/null 2>&1 || true
        timeout 120 $SUDO env DEBIAN_FRONTEND=noninteractive dpkg --configure -a > /dev/null 2>&1 || true
    fi
}

echo "  [1/5] Pakiety systemowe (Python, venv)..."
cleanup_msfonts
wait_for_apt
# błędy obcych repozytoriów (np. wygasły klucz Spotify/Chrome) nie mogą przerwać instalacji
$SUDO apt-get update -qq || true
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip > /dev/null

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
wait_for_apt
$SUDO .venv/bin/python -m playwright install-deps chromium > /dev/null
.venv/bin/python -m playwright install chromium

echo "  [4/5] Fonty (zamienniki Arial/Times/Calibri o identycznych wymiarach) + emoji..."
wait_for_apt
# Darmowe odpowiedniki fontów Windows: Liberation = Arial/Times New Roman/Courier New,
# Carlito = Calibri, Caladea = Cambria. Zwykłe paczki, nic nie pobierają przy instalacji.
for pkg in fonts-liberation fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea \
           fonts-dejavu-core fonts-noto-color-emoji; do
    timeout 300 $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$pkg" > /dev/null 2>&1 || true
done
fc-cache -f > /dev/null 2>&1 || true

echo "  [5/5] Test przeglądarki..."
chmod +x snap.sh
if ! .venv/bin/python snap.py --check; then
    echo ""
    echo "  ❌ Instalacja nie skończyła się poprawnie — skopiuj komunikat powyżej i zgłoś."
    exit 1
fi

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
