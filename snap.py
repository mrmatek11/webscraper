#!/usr/bin/env python3
"""
snap.py — Web Snapshot Tool (Wersja 1:1 + Fix na Lazy Load obrazków)
"""

import argparse
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin, urldefrag

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
"""

ASSET_EXTENSIONS = {
    '.css', '.js',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.avif', '.ico',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.mp4', '.webm', '.ogg', '.mp3',
    '.json',
}

CONTENT_TYPE_MAP = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
    'image/webp': '.webp', 'image/avif': '.avif', 'image/svg+xml': '.svg',
    'image/x-icon': '.ico', 'image/vnd.microsoft.icon': '.ico',
    'font/woff': '.woff', 'font/woff2': '.woff2', 'font/ttf': '.ttf',
    'font/otf': '.otf', 'application/font-woff': '.woff',
    'application/font-woff2': '.woff2', 'application/x-font-ttf': '.ttf',
    'text/css': '.css', 'application/javascript': '.js', 'text/javascript': '.js',
    'application/json': '.json',
}

NORMAL_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


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

def url_to_local_path(asset_url: str, assets_dir: Path, fname_counts: dict, content_type: str = ""):
    parsed = urlparse(asset_url)
    path_part = parsed.path.rstrip('/')
    base = Path(path_part).name or 'asset'
    base = sanitize_name(base).split('?')[0] or 'asset'

    if not Path(base).suffix:
        guessed_ext = '.bin'
        for ct_key, ct_ext in CONTENT_TYPE_MAP.items():
            if ct_key in content_type:
                guessed_ext = ct_ext
                break
        base += guessed_ext

    key = base
    if key in fname_counts:
        fname_counts[key] += 1
        stem = Path(base).stem
        ext = Path(base).suffix
        base = f"{stem}_{fname_counts[key]}{ext}"
    else:
        fname_counts[key] = 0

    abs_path = assets_dir / base
    return f"assets/{base}", abs_path


# ─── popup killing ────────────────────────────────────────────────────────────

def inject_anti_popup_css(page):
    try:
        page.evaluate("""
            () => {
                if (document.getElementById('__snap_anti_popup__')) return;
                const style = document.createElement('style');
                style.id = '__snap_anti_popup__';
                style.textContent = `
                    .modal-backdrop { display: none !important; }
                    #cookies_message_modal, #cookies_message { display: none !important; }
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

    for _ in range(3):
        try:
            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
        except Exception:
            pass

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
    inject_anti_popup_css(page)
    for attempt in range(4):
        close_popups(page)
        if attempt < 3:
            page.wait_for_timeout(1500)
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


# ─── navigation helpers ───────────────────────────────────────────────────────

def _scroll_and_wait(page):
    try:
        page.evaluate("""
            async () => {
                await new Promise(resolve => {
                    let total = 0;
                    const step = 300;
                    const dist = document.body.scrollHeight;
                    const timer = setInterval(() => {
                        window.scrollBy(0, step);
                        total += step;
                        if (total >= dist) {
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

def _force_lazy_load(page):
    """Brutalnie wymusza załadowanie obrazków typu data-lazy-src (LiteSpeed, WP Rocket itp.)"""
    try:
        page.evaluate("""
            () => {
                // Wymuszenie dla LiteSpeed Cache / WP Rocket (data-lazy-src)
                document.querySelectorAll('img[data-lazy-src]').forEach(img => {
                    img.src = img.getAttribute('data-lazy-src');
                    if (img.getAttribute('data-lazy-srcset')) {
                        img.srcset = img.getAttribute('data-lazy-srcset');
                    }
                    if (img.getAttribute('data-lazy-sizes')) {
                        img.sizes = img.getAttribute('data-lazy-sizes');
                    }
                    img.classList.remove('lazyloading', 'lazyload');
                    img.classList.add('lazyloaded');
                });
                
                // Wymuszenie dla natywnego lazy loading (loading="lazy")
                document.querySelectorAll('img[loading="lazy"]').forEach(img => {
                    img.loading = 'eager';
                });
            }
        """)
        page.wait_for_timeout(500) # Czekamy ułamek sekundy aż przeglądarka zacznie pobierać prawdziwe pliki
    except Exception:
        pass

def _force_slider_render(page):
    """Przesuwa Flickity slajdy jeden po drugim, wymuszając lazy-load każdego zdjęcia."""
    try:
        page.wait_for_function("""
            () => typeof window.Flickity !== 'undefined' ||
                  document.querySelector('.flickity-enabled') !== null
        """, timeout=8000)
    except Exception:
        pass

    try:
        page.evaluate("""
            () => {
                const carousels = document.querySelectorAll('.deeper-carousel-box');
                carousels.forEach(carousel => {
                    const items = carousel.querySelectorAll('.deeper-fancy-image');
                    const count = items.length;
                    if (!count) return;

                    const flkty = window.Flickity && window.Flickity.data
                        ? window.Flickity.data(carousel)
                        : null;

                    for (let i = 0; i < count; i++) {
                        if (flkty) flkty.select(i, false, true);

                        items[i].querySelectorAll('img[data-lazy-src], img[src*="svg+xml"]').forEach(img => {
                            const real = img.getAttribute('data-lazy-src');
                            if (real) {
                                img.src = real;
                                img.classList.remove('lazyloading', 'lazyload');
                                img.classList.add('lazyloaded');
                            }
                        });
                    }

                    if (flkty) flkty.select(0, false, true);
                });
            }
        """)
        page.wait_for_timeout(2000)
    except Exception:
        pass

def _wait_for_images(page, timeout=5000):
    try:
        page.wait_for_function("""
            () => {
                const images = Array.from(document.querySelectorAll('img'));
                return images.length === 0 || images.every(img => img.complete);
            }
        """, timeout=timeout)
    except Exception:
        pass

def _wait_for_fonts(page):
    try:
        page.evaluate("async () => { await document.fonts.ready; }")
        page.wait_for_timeout(500)
    except Exception:
        pass

def _set_consent_cookies(context, url: str):
    try:
        domain = urlparse(url).netloc
        names = [
            'cookies_message_bar_hidden',
            'cookie_consent', 'cookie_accepted', 'cookies_accepted',
            'cookieconsent_status', 'CookieConsent', 'cc_cookie_accept',
            'gdpr_consent', 'consent',
            'cookies_google_analytics', 'cookies_google_targeting',
            'cookies_google_personalization', 'cookies_google_user_data',
        ]
        context.add_cookies([
            {'name': n, 'value': 'true', 'domain': domain, 'path': '/'}
            for n in names
        ])
    except Exception:
        pass

def _do_cleanup(page, aggressive: bool):
    if aggressive:
        close_popups_aggressive(page)
    else:
        close_popups(page)

def _navigate(page, url: str) -> bool:
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


# ─── asset capture via network interception ───────────────────────────────────

def _make_response_handler(assets_dir: Path, captured: dict, fname_counts: dict):
    def handle_response(response):
        try:
            req_url, _ = urldefrag(response.url)
            if req_url in captured:
                return
            if response.request.resource_type == 'document':
                return
            if response.status < 200 or response.status >= 400:
                return

            content_type = response.headers.get('content-type', '').lower()
            parsed_path = urlparse(req_url).path
            ext = Path(parsed_path).suffix.lower()
            rt = response.request.resource_type

            is_media_ct = any(t in content_type for t in ('image/', 'font/', 'text/css', 'javascript', 'audio/', 'video/'))
            
            if ext not in ASSET_EXTENSIONS and rt not in ('stylesheet', 'script', 'image', 'font', 'media') and not is_media_ct:
                return

            body = response.body()
            if not body:
                return

            local_rel, abs_path = url_to_local_path(req_url, assets_dir, fname_counts, content_type)
            abs_path.write_bytes(body)
            captured[req_url] = local_rel
            
            if response.url != req_url:
                captured[response.url] = local_rel

        except Exception:
            pass

    return handle_response


def _rewrite_html(html: str, captured: dict, page_url: str) -> str:
    if not captured:
        return html

    if '<base ' not in html.lower():
        html = html.replace('<head>', '<head>\n<base href=".">', 1)

    rewrites = {}

    for asset_url, local_rel in captured.items():
        rewrites[asset_url] = local_rel
        p = urlparse(asset_url)
        proto_rel = '//' + p.netloc + p.path + ('?' + p.query if p.query else '')
        if proto_rel not in rewrites:
            rewrites[proto_rel] = local_rel
        path_only = p.path
        if path_only and path_only not in rewrites:
            rewrites[path_only] = local_rel
        path_q = p.path + ('?' + p.query if p.query else '')
        if path_q and path_q not in rewrites:
            rewrites[path_q] = local_rel

    for original in sorted(rewrites, key=len, reverse=True):
        local = rewrites[original]
        if not original or original == local:
            continue
        escaped = re.escape(original)
        
        html = re.sub(
            r'((?:src|href|data-src|data-bg|poster|content)\s*=\s*["\'])(' + escaped + r')(["\'])',
            r'\g<1>' + local + r'\3',
            html,
            flags=re.IGNORECASE
        )
        
        html = re.sub(
            r'(url\(\s*["\']?)(' + escaped + r')(["\']?\s*\))',
            r'\g<1>' + local + r'\3',
            html,
            flags=re.IGNORECASE
        )

    return html

def _convert_blobs_to_base64(page):
    try:
        page.evaluate("""
            async () => {
                const images = document.querySelectorAll('img[src^="blob:"]');
                for (const img of images) {
                    try {
                        const response = await fetch(img.src);
                        const blob = await response.blob();
                        const reader = new FileReader();
                        const base64 = await new Promise((resolve) => {
                            reader.onloadend = () => resolve(reader.result);
                            reader.readAsDataURL(blob);
                        });
                        img.src = base64;
                    } catch (e) {
                        console.error('Failed to convert blob img', e);
                    }
                }
                
                const elements = document.querySelectorAll('[style*="blob:"]');
                elements.forEach(el => {
                    let style = el.getAttribute('style');
                    style = style.replace(/url\(["']?blob:[^"'\)]+["']?\)/g, (match) => {
                        return 'url(none)';
                    });
                    el.setAttribute('style', style);
                });
            }
        """)
    except Exception:
        pass


# ─── process functions ────────────────────────────────────────────────────────

def process_full(url: str, context, output_dir: Path, aggressive: bool = False) -> tuple:
    assets_dir = output_dir / 'assets'
    assets_dir.mkdir(parents=True, exist_ok=True)

    captured = {}
    fname_counts = {}

    _set_consent_cookies(context, url)
    page = context.new_page()
    page.on('response', _make_response_handler(assets_dir, captured, fname_counts))

    if not _navigate(page, url):
        page.close()
        return False, False

    _do_cleanup(page, aggressive)
    _scroll_and_wait(page)
    
    # NOWOŚĆ: Wymuszamy podmianę data-lazy-src na src zanim sprawdzimy czy obrazki się załadowały
    _force_lazy_load(page)
    _force_slider_render(page)
    
    _do_cleanup(page, aggressive)
    _wait_for_images(page)
    _wait_for_fonts(page)

    try:
        page.wait_for_timeout(1000)
    except Exception:
        pass

    _convert_blobs_to_base64(page)

    html_ok = False
    try:
        html = page.content()
        html = _rewrite_html(html, captured, url)
        (output_dir / 'index.html').write_text(html, encoding='utf-8', errors='replace')
        unique_assets = len(set(captured.values()))
        print(f"   assets: {unique_assets} files saved")
        html_ok = True
    except Exception as e:
        print(f"   [HTML ERR] {e}")

    shot_ok = False
    try:
        page.screenshot(path=str(output_dir / 'screenshot_full.png'), full_page=True)
        shot_ok = True
    except Exception as e:
        print(f"   [SHOT ERR] {e}")

    page.close()
    return html_ok, shot_ok


def process_screenshot_only(url: str, context, output_path: Path, aggressive: bool = False) -> bool:
    _set_consent_cookies(context, url)
    page = context.new_page()

    if not _navigate(page, url):
        page.close()
        return False

    _do_cleanup(page, aggressive)
    _scroll_and_wait(page)
    
    # NOWOŚĆ: To samo dla screenów
    _force_lazy_load(page)
    _force_slider_render(page)
    
    _do_cleanup(page, aggressive)
    _wait_for_images(page)
    _wait_for_fonts(page)

    try:
        page.screenshot(path=str(output_path), full_page=True)
        kb = output_path.stat().st_size // 1024
        print(f"   saved  {output_path.name}  ({kb} KB)")
        page.close()
        return True
    except Exception as e:
        print(f"   [SHOT ERR] {e}")
        page.close()
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

    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except ImportError:
        print("[!] Playwright not installed.")
        sys.exit(1)

    aggressive = mode.startswith('clean-')
    effective = mode.replace('clean-', '', 1)
    mode_label = f"CLEAN + {effective.upper()}" if aggressive else effective.upper()

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
                ctx = browser.new_context(
                    viewport={'width': 1440, 'height': 900},
                    bypass_csp=True,
                    user_agent=NORMAL_USER_AGENT
                )
                success = process_screenshot_only(url, ctx, out_path, aggressive=aggressive)
                ctx.close()
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

                ctx = browser.new_context(
                    viewport={'width': 1440, 'height': 900},
                    bypass_csp=True,
                    user_agent=NORMAL_USER_AGENT
                )
                html_ok, shot_ok = process_full(url, ctx, page_dir, aggressive=aggressive)
                ctx.close()

                print('[OK]' if (html_ok or shot_ok) else '[FAIL]')

            pack_dir_to_zip(domain_tmp, zip_path)
            if not keep_folders:
                shutil.rmtree(domain_tmp)

    browser.close()
    pw.stop()

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

def main():
    print(BANNER)

    VALID_MODES = ('full', 'screenshots', 'clean-full', 'clean-screenshots')

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