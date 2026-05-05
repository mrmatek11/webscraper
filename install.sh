#!/usr/bin/env bash
set -e

echo ""
echo "  snap.py — installer"
echo "  ───────────────────"
echo ""

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  [!] Python 3 not found. Install Python 3.8+ first."
    exit 1
fi

PYVER=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python: $PYTHON ($PYVER)"

echo ""
echo "  [1/3] Installing pip dependencies..."
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet -r requirements.txt

echo "  [2/3] Installing Playwright browsers..."
$PYTHON -m playwright install chromium

echo "  [3/3] Done!"
echo ""
echo "  Usage:"
echo "    $PYTHON snap.py https://example.com"
echo "    $PYTHON snap.py https://example.com --mode screenshots"
echo "    $PYTHON snap.py https://example.com --mode crawl --max-pages 50"
echo "    $PYTHON snap.py -f lista_stron.txt --mode full -o ./results"
echo ""
