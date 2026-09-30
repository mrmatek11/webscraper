#!/usr/bin/env bash
# Uruchamia snap.py z lokalnego środowiska .venv (utworzonego przez install.sh).
# Ścieżki (lista_stron.txt, results/) są liczone względem folderu projektu.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -x .venv/bin/python ]; then
    echo "[!] Brak instalacji — najpierw uruchom:  bash install.sh"
    read -r -p "Enter, aby zamknąć..." _
    exit 1
fi

.venv/bin/python snap.py "$@"
status=$?

# uruchomione dwuklikiem (bez argumentów) — nie zamykaj od razu okna terminala
if [ $# -eq 0 ] && [ -t 0 ]; then
    echo ""
    read -r -p "Gotowe. Wyniki są w folderze results/. Enter, aby zamknąć..." _
fi
exit $status
