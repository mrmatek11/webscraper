#!/usr/bin/env python3
"""
snap.py — Web Snapshot Tool
--mode full              : rendered HTML + assets + screenshots -> ZIP per domain
--mode screenshots       : screenshots only -> flat ZIP, files named by domain+date
--mode clean-full        : aggressive popup nuke, then HTML + assets + screenshots
--mode clean-screenshots : aggressive popup nuke, then screenshots only

Requirements:
    pip install playwright requests
    playwright install chromium
"""

import argparse
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests

BANNER = r"""
  ██████  ███▄    █  ▄▄▄       ██▓███
▒██    ▒  ██ ▀█   █ ▒████▄    ▓██░  ██▒
░ ▓██▄   ▓██  ▀█ ██▒▒██  ▀█▄  ▓██░ ██▓▒
  ▒   ██▒▓██▒  ▐▌██▒░██▄▄▄▄██ ▒██▄█▓▒ ▒
▒██████▒▒▒██░   ▓██░ ▓█   ▓██▒▒██▒ ░  ░
▒ ▒▓▒ ▒ ░░ ▒░   ▒ ▒  ▒▒   ▓▒█░▒▓▒░ ░  ░
░ ░▒  ░ ░░ ░░   ░ ▒░  ▒   ▒▒ ░░▒ ░
░  ░  ░     ░   ░ ░   ░   ▒   ░░
      ░           ░       ░  ░
  [ web snapshot tool ]  by snap.py
  ──────────────────────────────────────
  --mode full                HTML + assets + screenshots
  --mode screenshots         screenshots only  (fast)
  --mode clean-full          nuke popups, then full
  --mode clean-screenshots   nuke popups, then screenshots
"""


# ─── helpers ──────────────────────────────────────────────────────────────────

def sanitize_name(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name).strip('_')


def get_domain(url: str) -> str:
    return urlparse(url).netloc.replace('www.', '')


def get_subfolder_name(url: str) -> str:
    path = urlparse(url).path.strip('/')
    if not path:
        return 'homepage'
    name = sanitize_name(path.replace('/', '_'))
    return name[:80]


def get_zip_name(domain: str) -> str:
    return f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}_{sanitize_name(domain)}.zip"


def get_screenshot_filename(url: str) -> str:
    domain = get_domain(url)
    sub = get_subfolder_name(url)
    date = datetime.now().strftime('%Y-%m-%d')
    name = f"{date}_{sanitize_name(domain)}"
    if sub != 'homepage':
        name += f"_{sub}"
    return f"{name}.png"


# ─── html + assets ────────────────────────────────────────────────────────────

def save_html_with_assets(html_content: str, url: str, output_dir: Path, session: requests.Session) -> bool:
    assets_dir = output_dir / 'assets'
    assets_dir.mkdir(exist_ok=True)

    patterns = [
        (r'href=["\']([^"\']+\.css[^"\']*)["\']', 'css'),
        (r'<script[^>]*src=["\']([^"\']+\.js[^"\']*)["\']', 'js'),
        (r'<img[^>]*src=["\']([^"\']+\.(png|jpg|jpeg|gif|svg|webp|avif|ico)[^"\']*)["\']', 'img'),
        (r'<[^>]*data-src=["\']([^"\']+\.(png|jpg|jpeg|gif|svg|webp|avif)[^"\']*)["\']', 'img'),
        (r'<[^>]*data-bg=["\']([^"\']+\.(png|jpg|jpeg|gif|svg|webp|avif)[^"\']*)["\']', 'img'),
        (r'url\(["\']?([^"\')\s]+\.(png|jpg|jpeg|gif|svg|webp|woff2?|ttf|eot|otf)[^"\')\s]*)["\']?\)', 'asset'),
    ]

    srcset_urls = set()
    for match in re.finditer(r'<[^>]*srcset=["\']([^"\']+)["\']', html_content, re.IGNORECASE):
        for part in match.group(1).split(','):
            src = part.strip().split(' ')[0]
            if src and not src.startswith('data:'):
                srcset_urls.add(src)

    downloaded = {}
    for pattern, asset_type in patterns:
        for match in re.finditer(pattern, html_content, re.IGNORECASE):
            raw = match.group(1)
            if raw.startswith('data:'):
                continue
            if raw.startswith('//'):
                raw = 'https:' + raw
            full = urljoin(url, raw)
            if full not in downloaded:
                downloaded[full] = (asset_type, raw)

    for src in srcset_urls:
        if src.startswith('//'):
            src = 'https:' + src
        full = urljoin(url, src)
        if full not in downloaded:
            downloaded[full] = ('img', src)

    saved = {}
    for asset_url, (asset_type, _) in downloaded.items():
        try:
            r = session.get(asset_url, timeout=15)
            r.raise_for_status()
            fname = sanitize_name(Path(urlparse(asset_url).path).name) or f'asset_{len(saved)}'
            if not Path(fname).suffix:
                fname += f'.{asset_type}'
            (assets_dir / fname).write_bytes(r.content)
            saved[asset_url] = f'assets/{fname}'
            raw_path = urlparse(asset_url).path
            if raw_path:
                html_content = html_content.replace(raw_path, f'assets/{fname}')
        except requests.RequestException:
            pass

    for orig, local in saved.items():
        html_content = html_content.replace(orig, local)

    (output_dir / 'index.html').write_text(html_content, encoding='utf-8', errors='replace')
    return True


# ─── popup killing ────────────────────────────────────────────────────────────

def inject_anti_popup_css(page):
    """Inject CSS that prevents popups from ever becoming visible."""
    try:
        page.evaluate("""
            () => {
                if (document.getElementById('__snap_anti_popup__')) return;
                const style = document.createElement('style');
                style.id = '__snap_anti_popup__';
                style.textContent = `
                    .modal-backdrop { display: none !important; }
                    #cookies_message_modal { display: none !important; }
                    #cookies_message { display: none !important; }
                    [id*="cookie-banner"], [class*="cookie-banner"],
                    [id*="cookiebar"], [class*="cookiebar"],
                    [id*="cookie-notice"], [class*="cookie-notice"],
                    [id*="cookie-consent"], [class*="cookie-consent"],
                    [id*="gdpr-banner"], [class*="gdpr-banner"],
                    .cookie-modal, .cookie_modal,
                    [id*="newsletter-popup"], [class*="newsletter-popup"],
                    [id*="newsletter-modal"], [class*="newsletter-modal"],
                    [class*="consent-banner"], [id*="consent-banner"],
                    [id*="CybotCookiebot"], [class*="cookieconsent"],
                    [id*="onetrust"], [class*="onetrust"],
                    [id*="borlabs"], [class*="borlabs"],
                    [id*="iubenda"], [class*="iubenda"],
                    [id*="klaro"], [class*="klaro"],
                    [id*="tarteaucitron"], [class*="tarteaucitron"],
                    [id*="cookielaw"], [class*="cookielaw"],
                    [id*="fancybox-container"], [class*="fancybox-container"],
                    [id*="mfp-popup"], [class*="mfp-wrap"],
                    [class*="age-gate"], [id*="age-gate"],
                    [class*="exit-intent"], [id*="exit-intent"],
                    [class*="push-notification"], [id*="push-notification"]
                    { display: none !important; }
                `;
                document.head.appendChild(style);
            }
        """)
    except Exception:
        pass


def close_popups(page):
    """Dismiss popups/modals — single pass."""
    # ── Phase 1: click dismiss/accept/deny buttons ───────────────────────
    dismiss_selectors = [
        '#cookies-close-deny', '#cookies-close-accept', '#cookies-close-settings',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll',
        '.cc-dismiss', '.cc-btn.cc-dismiss',
        '.cookie-accept', '.cookie-close', '.consent-accept',
        '[class*="cookie"] .btn-primary', '[class*="cookie"] .btn-success',
        '[class*="consent"] .btn-primary', '[class*="gdpr"] .btn-primary',
        '[id*="cookie"] .btn-primary', '[id*="consent"] .btn-primary',
        'button.close', 'button[aria-label="Close"]', 'button[aria-label="close"]',
        'a.close', 'a[aria-label="Close"]', 'a[aria-label="close"]',
        '[data-dismiss="modal"]', '[data-bs-dismiss="modal"]',
        '.fancybox-close', '.fancybox-button--close', '.mfp-close',
        '[class*="close-btn"]', '[class*="closeBtn"]',
        '[class*="close-button"]', '[class*="popup-close"]',
        '[class*="modal-close"]',
        '[class*="newsletter"] [class*="close"]',
        '[class*="newsletter"] [class*="Close"]',
        '[id*="newsletter"] [class*="close"]',
        '[class*="popup"] [class*="close"]',
        '[class*="popup"] [class*="Close"]',
        '[id*="popup"] [class*="close"]',
        '[class*="overlay"] [class*="close"]',
        'svg[class*="close"]', 'svg[aria-label="Close"]', 'svg[aria-label="close"]',
        'img[alt="Close"]', 'img[alt="Zamknij"]', 'img[alt="zamknij"]',
    ]
    for selector in dismiss_selectors:
        try:
            els = page.query_selector_all(selector)
            for el in els:
                if el.is_visible():
                    el.click()
                    page.wait_for_timeout(400)
        except Exception:
            pass

    # ── Phase 2: Escape ×3 for stacked modals ───────────────────────────
    for _ in range(3):
        try:
            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
        except Exception:
            pass

    # ── Phase 3: nuclear JS ──────────────────────────────────────────────
    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
                document.querySelectorAll('.modal').forEach(modal => {
                    modal.classList.remove('in', 'show');
                    modal.style.display = 'none';
                    modal.setAttribute('aria-hidden', 'true');
                });
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.body.style.overflowY = '';
                document.body.style.paddingRight = '';
                document.documentElement.style.overflow = '';
                document.querySelectorAll(
                    '#cookies_message_modal, #cookies_message, ' +
                    '[id*="cookie-banner"], [id*="cookiebar"], [id*="cookie-notice"]'
                ).forEach(el => el.remove());
                document.querySelectorAll('*').forEach(el => {
                    const style = window.getComputedStyle(el);
                    if (style.position !== 'fixed' && style.position !== 'absolute') return;
                    const zIndex = parseInt(style.zIndex) || 0;
                    if (zIndex <= 1000) return;
                    if (el.closest('header, footer, nav, main, [id*="homepage"], [id*="sidebar"]')) return;
                    el.style.setProperty('display', 'none', 'important');
                });
            }
        """)
        page.wait_for_timeout(500)
    except Exception:
        pass


def close_popups_aggressive(page):
    """Multi-pass aggressive popup removal with CSS shielding."""
    inject_anti_popup_css(page)

    for attempt in range(4):
        close_popups(page)
        if attempt < 3:
            page.wait_for_timeout(1500)

    # final nuclear sweep
    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
                document.querySelectorAll('.modal').forEach(m => {
                    m.classList.remove('in', 'show');
                    m.style.display = 'none';
                });
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
                document.documentElement.style.overflow = '';
                // kill ANY remaining fixed/absolute overlay with high z-index
                document.querySelectorAll('*').forEach(el => {
                    const s = window.getComputedStyle(el);
                    if (s.position !== 'fixed' && s.position !== 'absolute') return;
                    if ((parseInt(s.zIndex) || 0) <= 1000) return;
                    if (el.closest('header, footer, nav, main, [id*="homepage"], [id*="sidebar"]')) return;
                    el.style.setProperty('display', 'none', 'important');
                });
            }
        """)
        page.wait_for_timeout(300)
    except Exception:
        pass


# ─── navigation + processing ──────────────────────────────────────────────────

def scroll_and_wait(page):
    try:
        page.evaluate("""
            async () => {
                await new Promise(resolve => {
                    let total = 0;
                    const step = 300;
                    const timer = setInterval(() => {
                        window.scrollBy(0, step);
                        total += step;
                        if (total >= document.body.scrollHeight) {
                            clearInterval(timer);
                            window.scrollTo(0, 0);
                            resolve();
                        }
                    }, 100);
                });
            }
        """)
        page.wait_for_timeout(1500)
    except Exception:
        pass


def goto_page(page, url: str) -> bool:
    try:
        domain = urlparse(url).netloc
        consent_cookies = [
            'cookies_message_bar_hidden',
            'cookie_consent', 'cookie_accepted', 'cookies_accepted',
            'cookieconsent_status', 'CookieConsent', 'cc_cookie_accept',
            'gdpr_consent', 'consent',
            'cookies_google_analytics', 'cookies_google_targeting',
            'cookies_google_personalization', 'cookies_google_user_data',
        ]
        page.context.add_cookies([
            {'name': name, 'value': 'true', 'domain': domain, 'path': '/'}
            for name in consent_cookies
        ])
    except Exception:
        pass

    try:
        page.goto(url, wait_until='networkidle', timeout=60000)
        return True
    except Exception:
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            return True
        except Exception as e:
            print(f" [NAV ERR] {e}")
            return False


def _do_cleanup(page, aggressive: bool):
    """Run popup cleanup (normal or aggressive)."""
    if aggressive:
        close_popups_aggressive(page)
    else:
        close_popups(page)


def process_full(url: str, page, session, output_dir: Path, aggressive: bool = False) -> tuple:
    if not goto_page(page, url):
        return False, False
    _do_cleanup(page, aggressive)
    scroll_and_wait(page)
    _do_cleanup(page, aggressive)
    html_ok = False
    shot_ok = False
    try:
        html_ok = save_html_with_assets(page.content(), url, output_dir, session)
    except Exception:
        pass
    try:
        page.screenshot(path=str(output_dir / 'screenshot_full.png'), full_page=True)
        shot_ok = True
    except Exception:
        pass
    return html_ok, shot_ok


def process_screenshot_only(url: str, page, output_path: Path, aggressive: bool = False) -> bool:
    if not goto_page(page, url):
        return False
    _do_cleanup(page, aggressive)
    scroll_and_wait(page)
    _do_cleanup(page, aggressive)
    try:
        page.screenshot(path=str(output_path), full_page=True)
        kb = output_path.stat().st_size // 1024
        print(f"   saved  {output_path.name}  ({kb} KB)")
        return True
    except Exception as e:
        print(f"   [SHOT ERR] {e}")
        return False


# ─── zip helpers ──────────────────────────────────────────────────────────────

def pack_dir_to_zip(src_dir: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob('*'):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir.parent))
    mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  [ZIP]  {zip_path.name}  ({mb:.1f} MB)")


def pack_files_to_zip(files: list, zip_path: Path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  [ZIP]  {zip_path.name}  ({mb:.1f} MB)")


# ─── main processing ──────────────────────────────────────────────────────────

def run(urls: list, base_output: Path, mode: str, keep_folders: bool = False):
    normalized = [u if u.startswith(('http://', 'https://')) else 'https://' + u for u in urls]

    session = requests.Session()
    session.headers.update({'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/125.0.0.0 Safari/537.36'
    )})

    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except ImportError:
        print("[!] Playwright not installed.")
        sys.exit(1)

    # resolve mode + aggressive flag
    aggressive = mode.startswith('clean-')
    effective = mode.replace('clean-', '', 1)  # 'full' or 'screenshots'

    mode_label = f"CLEAN + {effective.upper()}" if aggressive else effective.upper()

    session = requests.Session()
    session.headers.update({'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/125.0.0.0 Safari/537.36'
    )})

    # ── screenshots only ──────────────────────────────────────────────────
    if effective == 'screenshots':
        print(f"\n  mode  : {mode_label}")
        print(f"  pages : {len(normalized)}\n")

        by_domain = defaultdict(list)
        for url in normalized:
            by_domain[get_domain(url)].append(url)

        tmp_dir = base_output / '_screenshots_tmp'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ok = fail = 0

        for domain, domain_urls in by_domain.items():
            print(f"\n  [*] {domain}  ({len(domain_urls)} pages)")
            domain_shots = []

            for url in domain_urls:
                fname = get_screenshot_filename(url)
                out_path = tmp_dir / fname
                print(f"      >> {url}")
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                success = process_screenshot_only(url, page, out_path, aggressive=aggressive)
                page.close()
                if success:
                    domain_shots.append(out_path)
                    ok += 1
                else:
                    fail += 1

            if domain_shots:
                zip_path = base_output / get_zip_name(domain)
                pack_files_to_zip(domain_shots, zip_path)

        shutil.rmtree(tmp_dir)
        print(f"\n  done  : {ok} ok  /  {fail} failed")

    # ── full mode ─────────────────────────────────────────────────────────
    else:
        by_domain = defaultdict(list)
        for url in normalized:
            by_domain[get_domain(url)].append(url)

        print(f"\n  mode    : {mode_label}")
        print(f"  domains : {len(by_domain)}")
        print(f"  pages   : {len(normalized)}\n")

        for domain, domain_urls in by_domain.items():
            zip_path = base_output / get_zip_name(domain)
            domain_tmp = base_output / sanitize_name(domain)
            domain_tmp.mkdir(parents=True, exist_ok=True)

            print(f"\n  [*] {domain}  ({len(domain_urls)} pages)")

            for url in domain_urls:
                sub = get_subfolder_name(url)
                page_dir = domain_tmp / sub
                page_dir.mkdir(parents=True, exist_ok=True)
                (page_dir / 'meta.txt').write_text(
                    f"URL: {url}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
                    encoding='utf-8'
                )
                print(f"      -> {sub}/", end='  ')
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                html_ok, shot_ok = process_full(url, page, session, page_dir, aggressive=aggressive)
                page.close()
                print('[OK]' if (html_ok or shot_ok) else '[FAIL]')

            pack_dir_to_zip(domain_tmp, zip_path)
            if not keep_folders:
                shutil.rmtree(domain_tmp)

    browser.close()
    pw.stop()

    # ── summary ───────────────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("  RESULTS")
    print("─" * 50)
    for z in sorted(base_output.glob('*.zip')):
        mb = z.stat().st_size / (1024 * 1024)
        print(f"  {z.name}  ({mb:.1f} MB)")
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
        if all(len(Path(n).parts) == 1 for n in names):
            for n in sorted(names):
                print(f"      |-- {n}")
        else:
            folders = sorted(set(
                str(Path(n).parts[1]) for n in names if len(Path(n).parts) > 1
            ))
            for f in folders:
                print(f"      |-- {f}/")
    print()


# ─── interactive prompt ───────────────────────────────────────────────────────

def prompt_mode() -> tuple:
    """Returns (effective_mode, aggressive)."""
    print("  select mode:")
    print()
    print("    [1]  full              HTML + assets + screenshots")
    print("    [2]  screenshots       screenshots only  (fast)")
    print("    [3]  clean             aggressive popup nuke, then choose ↓")
    print()
    while True:
        try:
            choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  aborted.")
            sys.exit(0)

        if choice in ('1', 'full'):
            return 'full', False
        if choice in ('2', 'screenshots', 'ss'):
            return 'screenshots', False
        if choice in ('3', 'clean'):
            print()
            print("  clean mode — after nuking popups:")
            print()
            print("    [1]  full          HTML + assets + screenshots")
            print("    [2]  screenshots   screenshots only")
            print()
            while True:
                try:
                    sub = input("  > ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n  aborted.")
                    sys.exit(0)
                if sub in ('1', 'full'):
                    return 'full', True
                if sub in ('2', 'screenshots', 'ss'):
                    return 'screenshots', True
                print("  [?] type 1 or 2")
        print("  [?] type 1, 2 or 3")


def prompt_urls() -> list:
    print()
    print("  url source:")
    print()
    print("    [1]  load from file   (lista_stron.txt or custom path)")
    print("    [2]  type URLs now")
    print()
    while True:
        try:
            choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  aborted.")
            sys.exit(0)

        if choice in ('1', 'file'):
            try:
                path_raw = input("  file path [lista_stron.txt]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  aborted.")
                sys.exit(0)
            fp = Path(path_raw if path_raw else 'lista_stron.txt')
            if not fp.exists():
                print(f"  [!] not found: {fp}")
                continue
            urls = []
            with open(fp) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        urls.append(line)
            if not urls:
                print("  [!] file is empty or all lines are comments")
                continue
            print(f"  loaded {len(urls)} URL(s) from {fp}")
            return urls

        if choice in ('2', 'type', 'manual'):
            print("  enter URLs one per line, empty line to finish:")
            urls = []
            while True:
                try:
                    line = input("  url> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    break
                urls.append(line)
            if not urls:
                print("  [!] no URLs entered, try again")
                continue
            return urls

        print("  [?] type 1 or 2")


def prompt_output() -> Path:
    try:
        raw = input("\n  output dir [./results]: ").strip()
    except (EOFError, KeyboardInterrupt):
        raw = ''
    out = Path(raw if raw else './results').expanduser()
    out.mkdir(parents=True, exist_ok=True)
    return out


# ─── entry point ──────────────────────────────────────────────────────────────

def main():
    print(BANNER)

    VALID_MODES = ('full', 'screenshots', 'clean-full', 'clean-screenshots')

    # if flags are passed, use them directly (non-interactive)
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description='snap.py — web snapshot tool')
        parser.add_argument('urls', nargs='*')
        parser.add_argument('-f', '--file')
        parser.add_argument('-o', '--output', default='./results')
        parser.add_argument('--mode', choices=VALID_MODES, default='full')
        parser.add_argument('--keep-folders', action='store_true')
        args = parser.parse_args()
        urls = list(args.urls)
        if args.file:
            fp = Path(args.file)
            if not fp.exists():
                print(f"[!] File not found: {args.file}")
                sys.exit(1)
            with open(fp) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        urls.append(line)
        if not urls:
            print("[!] Provide at least one URL.")
            sys.exit(1)
        seen = set()
        unique = [u for u in urls if not (u in seen or seen.add(u))]
        out = Path(args.output).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        run(unique, out, mode=args.mode, keep_folders=args.keep_folders)
        return

    # ── interactive ───────────────────────────────────────────────────────
    effective, aggressive = prompt_mode()
    mode = f"clean-{effective}" if aggressive else effective
    urls = prompt_urls()
    out = prompt_output()

    seen = set()
    unique = [u for u in urls if not (u in seen or seen.add(u))]

    mode_label = f"CLEAN + {effective.upper()}" if aggressive else effective.upper()

    print(f"\n  ── starting {'─'*35}")
    print(f"  mode   : {mode_label}")
    print(f"  pages  : {len(unique)}")
    print(f"  output : {out.resolve()}")
    print(f"  {'─'*44}\n")

    run(unique, out, mode=mode)


if __name__ == '__main__':
    main()