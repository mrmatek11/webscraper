#!/usr/bin/env python3
"""
snap.py — Web Snapshot Tool v3 (Ostateczna wersja hybrydowa)
Fixes:
  #1 - _navigate: usunięty wait_for_function z === (crash na redirectach)
  #2 - process_full: parametr page_url zamiast url (nie nadpisuje się przez pętlę img)
  #3 - get_zip_name: timestamp z sekundami (brak kolizji przy wielu domenach)
  #4 - _scroll_and_wait: timeout na JS evaluate (infinite scroll nie zawiesza)
  #5 - _force_slider_render: szybki check czy Flickity istnieje (nie czeka 8s)
  #6 - screenshot: limit wysokości 15000px (brak crashy na długich LP)
  #7 - _rewrite_html: mądra obsługa <base> (zostawia oryginalny zamiast usuwać)
Nowe z v3:
  - progress bar [n/total] przy każdej stronie
  - wypisywanie aktualnego URL przeglądarki po nawigacji
  - _force_sr7_render (obsługa Slider Revolution 7)
  - _force_revslider_render (obsługa starszego RevSlidera 6)
  - _disable_css_animations (wyłączanie animacji AOS/WOW)
  - _force_carousel_load_aggressive (agresywne klikanie karuzel)
"""

import argparse
import logging
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse, urljoin, urldefrag

import requests

BANNER = r"""
  ██████  ███▄    █  ▄▄▄       ██▓███
▒██    ▒  ██ ▀█   █ ▒████▄    ▓██░  ██▒
░ ▓██▄   ▓██  ▀█ ██▒▒██  ▀█▄  ▓██░ ██▓▒
  ▒   ██▒▓██▒  ▐▌██▒░██▄▄▄▄██ ▒██▄█▓▒ ▒
▒██████▒▒▒██░   ▓██░ ▓█   ▓██▒▒██▒ ░  ░
░ ' ▒▓▒ ▒ ░░ ' ░   ▒ ▒  ▒▒   ▓▒█░▒▓▒░ ░  ░
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

NORMAL_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

SCREENSHOT_MAX_HEIGHT = 15000

_log_file = None
_log_handler = None


def setup_logging(output_dir: Path):
    global _log_file, _log_handler
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    _log_file = output_dir / f"snap_{ts}.log"
    _log_handler = logging.FileHandler(_log_file, encoding='utf-8')
    _log_handler.setFormatter(logging.Formatter('%(asctime)s  %(message)s', datefmt='%H:%M:%S'))
    _log_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(_log_handler)
    logging.getLogger().setLevel(logging.INFO)
    return _log_file


# ─── sitemap / crawl ───────────────────────────────────────────────────────────

def fetch_sitemap_urls(base_url: str, session: requests.Session) -> list:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        urljoin(base_url, '/sitemap.xml'),
        urljoin(base_url, '/sitemap_index.xml'),
        urljoin(base_url, '/sitemap-index.xml'),
        urljoin(base_url, '/wp-sitemap.xml'),
    ]
    found = []
    for sm_url in candidates:
        try:
            r = session.get(sm_url, timeout=10, headers={'User-Agent': NORMAL_USER_AGENT})
            if r.status_code != 200:
                continue
            found.extend(_parse_sitemap_xml(r.text, origin))
        except Exception:
            continue
    return found


def _parse_sitemap_xml(xml_text: str, origin: str) -> list:
    urls = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return urls

    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'

    for sm_element in root.findall(f'{ns}sitemap') + root.findall('sitemap'):
        loc = sm_element.find(f'{ns}loc') or sm_element.find('loc')
        if loc is not None and loc.text:
            sm_url = loc.text.strip()
            try:
                r = requests.get(sm_url, timeout=10, headers={'User-Agent': NORMAL_USER_AGENT})
                if r.status_code == 200:
                    urls.extend(_parse_sitemap_xml(r.text, origin))
            except Exception:
                pass

    for url_element in root.findall(f'{ns}url') + root.findall('url'):
        loc = url_element.find(f'{ns}loc') or url_element.find('loc')
        if loc is not None and loc.text:
            url = loc.text.strip()
            if url.startswith(origin):
                urls.append(url)

    return urls


SKIP_EXTENSIONS = {
    '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.avif', '.ico',
    '.woff', '.woff2', '.ttf', '.eot', '.otf', '.mp4', '.webm', '.ogg', '.mp3',
    '.json', '.xml', '.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip',
    '.rar', '.gz', '.map', '.less', '.scss',
}

def crawl_internal_links(page_url: str, session: requests.Session, max_pages: int = 50,
                         same_domain_only: bool = True) -> list:
    parsed = urlparse(page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc

    try:
        r = session.get(page_url, timeout=15, headers={'User-Agent': NORMAL_USER_AGENT})
        if r.status_code != 200:
            return [page_url]
    except Exception:
        return [page_url]

    found_urls = {page_url}
    href_pat = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    seen = set()

    for m in href_pat.finditer(r.text):
        href = m.group(1).strip()
        if href.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:')):
            continue
        full = urljoin(page_url, href)
        full, _ = urldefrag(full)
        fp = urlparse(full)
        if not fp.scheme in ('http', 'https'):
            continue
        if fp.netloc != domain:
            continue
        ext = Path(fp.path).suffix.lower()
        if ext in SKIP_EXTENSIONS:
            continue
        clean = full.rstrip('/')
        if clean not in seen:
            seen.add(clean)
            if len(seen) > max_pages:
                break
            found_urls.add(clean)

    return sorted(found_urls)

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

def get_zip_name(domain: str, mode: str = 'full') -> str:
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    d = sanitize_name(domain)
    if mode == 'screenshots':
        return f"SCREENSHOTS_{ts}_{d}.zip"
    if mode == 'crawl':
        return f"CRAWL_{ts}_{d}.zip"
    return f"FULL_{ts}_{d}.zip"

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
        guessed_ext = '.dat'
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
                    [class*="push-notification"], [id*="push-notification"],
                    #mfn-gdpr { display: none !important; }
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
        '.mfn-gdpr-button',
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
                    '#cookies_message_modal, #cookies_message, #mfn-gdpr, ' +
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
            () => new Promise(resolve => {
                let total = 0;
                const step = 300;
                const dist = Math.min(document.body.scrollHeight, 30000);
                const timer = setInterval(() => {
                    window.scrollBy(0, step);
                    total += step;
                    if (total >= dist) {
                        clearInterval(timer);
                        window.scrollTo(0, 0);
                        resolve();
                    }
                }, 100);
                setTimeout(() => { clearInterval(timer); window.scrollTo(0, 0); resolve(); }, 8000);
            })
        """, timeout=10000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

def _force_lazy_load(page):
    try:
        page.evaluate("""
            () => {
                const applyImage = (img, src, srcset, sizes) => {
                    if (src) img.src = src;
                    if (srcset) img.srcset = srcset;
                    if (sizes) img.sizes = sizes;
                    img.classList.remove('lazyload', 'lazyloading');
                    img.classList.add('lazyloaded');
                };
                document.querySelectorAll('img').forEach(img => {
                    let src = img.getAttribute('data-lazy-src') || img.getAttribute('data-src') || img.getAttribute('data-original');
                    let srcset = img.getAttribute('data-lazy-srcset') || img.getAttribute('data-srcset');
                    let sizes = img.getAttribute('data-lazy-sizes') || img.getAttribute('data-sizes');
                    if (src || srcset) applyImage(img, src, srcset, sizes);
                    if (img.loading === 'lazy') img.loading = 'eager';
                });
                document.querySelectorAll('[data-bg], [data-lazy-bg]').forEach(el => {
                    let bg = el.getAttribute('data-bg') || el.getAttribute('data-lazy-bg');
                    if (bg) el.style.backgroundImage = 'url(' + bg + ')';
                });
                document.querySelectorAll('source').forEach(source => {
                    let srcset = source.getAttribute('data-lazy-srcset') || source.getAttribute('data-srcset');
                    if (srcset) source.srcset = srcset;
                });
            }
        """)
        page.wait_for_timeout(800)
    except Exception as e:
        print(f"   lazy load warning: {e}")

def _force_slider_render(page):
    try:
        has_flickity = page.evaluate("""
            () => typeof window.Flickity !== 'undefined' ||
                  document.querySelector('.flickity-enabled') !== null
        """)
    except Exception:
        has_flickity = False

    if not has_flickity:
        return

    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('.flickity-enabled').forEach(carousel => {
                    const flkty = window.Flickity?.data(carousel);
                    if (flkty && flkty.slides) {
                        const total = flkty.slides.length;
                        for (let i = 0; i < total; i++) flkty.select(i, false, true);
                        flkty.select(0, false, true);
                    }
                });
                const carousels = document.querySelectorAll('.deeper-carousel-box');
                carousels.forEach(carousel => {
                    const items = carousel.querySelectorAll('.deeper-fancy-image');
                    const count = items.length;
                    if (!count) return;
                    const flkty = window.Flickity && window.Flickity.data ? window.Flickity.data(carousel) : null;
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

def _force_sr7_render(page):
    """Handle Slider Revolution 7 (SR7) — custom web components + base64 data-dbsrc."""
    try:
        has_sr7 = page.evaluate("() => document.querySelector('sr7-module') !== null")
    except Exception:
        return
    if not has_sr7:
        return

    sr7_ready = False
    for _ in range(20):
        try:
            sr7_ready = page.evaluate("""
                () => {
                    if (window.SR7 && window.SR7.M) {
                        for (const k of Object.keys(window.SR7.M)) {
                            if (window.SR7.M[k] && window.SR7.M[k].state === true) return true;
                        }
                    }
                    const bgs = document.querySelectorAll('sr7-bg');
                    for (const bg of bgs) {
                        const s = window.getComputedStyle(bg);
                        if (s.backgroundImage && s.backgroundImage !== 'none') return true;
                    }
                    const canvases = document.querySelectorAll('sr7-module canvas');
                    for (const c of canvases) {
                        if (c.width > 100 && c.height > 100) return true;
                    }
                    return false;
                }
            """)
            if sr7_ready:
                break
        except Exception:
            pass
        page.wait_for_timeout(500)

    if sr7_ready:
        try:
            page.evaluate("""
                () => {
                    document.querySelectorAll('sr7-loader, .sr7-loader, .tp-loader, .rs-loader').forEach(el => el.style.setProperty('display', 'none', 'important'));
                    document.querySelectorAll('sr7-module').forEach(mod => {
                        mod.style.setProperty('visibility', 'visible', 'important');
                        mod.style.setProperty('opacity', '1', 'important');
                    });
                }
            """)
        except Exception:
            pass
        page.wait_for_timeout(500)
        return

    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('sr7-bg').forEach(bg => {
                    const noscript = bg.querySelector('noscript');
                    if (!noscript) return;
                    const tmp = document.createElement('div');
                    tmp.innerHTML = noscript.textContent || noscript.innerText;
                    const img = tmp.querySelector('img');
                    if (img && img.src) {
                        bg.style.setProperty('background-image', 'url(' + img.src + ')', 'important');
                        bg.style.setProperty('background-size', 'cover', 'important');
                        bg.style.setProperty('background-position', 'center center', 'important');
                        bg.style.setProperty('display', 'block', 'important');
                        bg.style.setProperty('position', 'absolute', 'important');
                        bg.style.setProperty('inset', '0', 'important');
                    }
                });
                document.querySelectorAll('sr7-module').forEach(mod => {
                    mod.style.setProperty('min-height', '100vh', 'important');
                    mod.style.setProperty('position', 'relative', 'important');
                    mod.style.setProperty('overflow', 'hidden', 'important');
                });
                document.querySelectorAll('sr7-content').forEach(c => {
                    c.style.setProperty('min-height', '100vh', 'important');
                    c.style.setProperty('position', 'relative', 'important');
                });
                document.querySelectorAll('sr7-slide').forEach(s => {
                    s.style.setProperty('min-height', '100vh', 'important');
                    s.style.setProperty('position', 'relative', 'important');
                    s.style.setProperty('display', 'block', 'important');
                });
                document.querySelectorAll('sr7-txt').forEach(t => {
                    t.style.setProperty('visibility', 'visible', 'important');
                    t.style.setProperty('opacity', '1', 'important');
                    t.style.setProperty('position', 'absolute', 'important');
                });
                document.querySelectorAll('sr7-slide > a.sr7-layer').forEach(a => {
                    a.style.setProperty('visibility', 'visible', 'important');
                    a.style.setProperty('opacity', '1', 'important');
                    a.style.setProperty('position', 'absolute', 'important');
                });
                document.querySelectorAll('sr7-loader, .sr7-loader, .tp-loader, .rs-loader').forEach(el => el.style.setProperty('display', 'none', 'important'));

                const imageLists = document.querySelector('image_lists');
                if (imageLists) {
                    imageLists.querySelectorAll('img[data-dbsrc]').forEach(img => {
                        try {
                            const url = atob(img.getAttribute('data-dbsrc'));
                            const full = url.startsWith('//') ? 'https:' + url : url;
                            const preload = new Image();
                            preload.src = full;
                        } catch(e) {}
                    });
                }

                if (window.SR7 && window.SR7.JSON) {
                    try {
                        Object.values(window.SR7.JSON).forEach(slider => {
                            if (!slider || !slider.slides) return;
                            Object.values(slider.slides).forEach(slide => {
                                if (!slide || !slide.slide || !slide.slide.layers) return;
                                Object.values(slide.slide.layers).forEach(layer => {
                                    if (layer && layer.bg && layer.bg.image && layer.bg.image.src) {
                                        new Image().src = layer.bg.image.src;
                                    }
                                });
                            });
                        });
                    } catch(e) {}
                }
            }
        """)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"   [SR7 fallback warning] {e}")

def _force_revslider_render(page):
    """Revolution Slider 6 (rs-module / rs-bg) — older WP plugin variant."""
    try:
        has_rs = page.evaluate("() => document.querySelector('rs-module') !== null")
    except Exception:
        return
    if not has_rs:
        return

    rs_ready = False
    for _ in range(15):
        try:
            rs_ready = page.evaluate("""
                () => {
                    if (window.revapi) {
                        if (typeof window.revapi === 'function') return true;
                        if (typeof window.revapi === 'object' && Object.keys(window.revapi).length > 0) {
                            const key = Object.keys(window.revapi)[0];
                            if (window.revapi[key] && window.revapi[key].revapis) return true;
                        }
                    }
                    const modules = document.querySelectorAll('rs-module');
                    for (const mod of modules) {
                        const bgs = mod.querySelectorAll('.rs-sbg, rs-sbg img, rs-sbg[style*="background"]');
                        if (bgs.length > 0 && bgs[0].getBoundingClientRect().width > 100) return true;
                    }
                    return false;
                }
            """)
            if rs_ready:
                break
        except Exception:
            pass
        page.wait_for_timeout(500)

    if rs_ready:
        try:
            page.evaluate("""
                () => {
                    document.querySelectorAll('.rs-loader, rs-loader, .tp-loader').forEach(el => {
                        el.style.setProperty('display', 'none', 'important');
                    });
                }
            """)
        except Exception:
            pass
        return

    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('rs-bg noscript, rs-sbg noscript').forEach(noscript => {
                    const tmp = document.createElement('div');
                    tmp.innerHTML = noscript.textContent || noscript.innerText;
                    const img = tmp.querySelector('img');
                    if (img && img.src) {
                        const parent = noscript.closest('rs-bg') || noscript.closest('rs-sbg');
                        if (parent) {
                            parent.style.setProperty('background-image', 'url(' + img.src + ')', 'important');
                            parent.style.setProperty('background-size', 'cover', 'important');
                        }
                    }
                });
                document.querySelectorAll('rs-sbg').forEach(sbg => {
                    sbg.style.setProperty('visibility', 'visible', 'important');
                    sbg.style.setProperty('opacity', '1', 'important');
                });
                document.querySelectorAll('.rs-loader, rs-loader, .tp-loader').forEach(el => {
                    el.style.setProperty('display', 'none', 'important');
                });
                document.querySelectorAll('rs-module').forEach(mod => {
                    mod.style.setProperty('visibility', 'visible', 'important');
                    mod.style.setProperty('opacity', '1', 'important');
                });
                document.querySelectorAll('.rs-layer[data-rr]').forEach(layer => {
                    layer.style.setProperty('visibility', 'visible', 'important');
                });
            }
        """)
        page.wait_for_timeout(1000)
    except Exception:
        pass

def _disable_css_animations(page):
    try:
        page.evaluate("""
            () => {
                const skip = 'header, nav, footer, [role="dialog"], [aria-hidden="true"], '
                    + '.cookie-banner, .modal, .popup, .tooltip, .dropdown, .submenu, '
                    + 'script, style, noscript, .nav__menu';
                document.querySelectorAll('*').forEach(el => {
                    if (el.closest(skip)) return;
                    const s = window.getComputedStyle(el);
                    if (parseFloat(s.opacity) < 0.1 && s.display !== 'none') {
                        el.style.setProperty('opacity', '1', 'important');
                        el.style.setProperty('visibility', 'visible', 'important');
                        el.style.setProperty('transform', 'none', 'important');
                        el.style.setProperty('transition', 'none', 'important');
                        el.style.setProperty('animation', 'none', 'important');
                    }
                });
                document.querySelectorAll('.image_frame .image_wrapper .image_links, .mask').forEach(el => {
                    el.style.opacity = '1';
                });
                window.dispatchEvent(new Event('scroll'));
                return new Promise(resolve => setTimeout(resolve, 100));
            }
        """)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"   [animations fix warning] {e}")

def _force_carousel_load_aggressive(page):
    try:
        for _ in range(10):
            page.evaluate("""
                () => {
                    document.querySelectorAll(
                        '.flickity-prev-next-button.next, .owl-next, .slick-next, .deeper-carousel-box .next'
                    ).forEach(btn => { if (btn.click) btn.click(); });
                }
            """)
            page.wait_for_timeout(500)
    except Exception:
        pass

def _force_elementor_render(page):
    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('.elementor-invisible').forEach(el => {
                    el.classList.remove('elementor-invisible', 'elementor-animation-fadeIn',
                        'elementor-animation-fadeInUp', 'elementor-animation-fadeInDown',
                        'elementor-animation-fadeInLeft', 'elementor-animation-fadeInRight',
                        'elementor-animation-slideInUp', 'elementor-animation-slideInDown',
                        'elementor-animation-slideInLeft', 'elementor-animation-slideInRight',
                        'elementor-animation-zoomIn', 'elementor-animation-bounceIn',
                        'elementor-animation-pulse', 'elementor-animation-bob',
                        'elementor-animation-grow');
                    el.style.setProperty('opacity', '1', 'important');
                    el.style.setProperty('visibility', 'visible', 'important');
                    el.style.setProperty('transform', 'none', 'important');
                    el.style.setProperty('transition', 'none', 'important');
                    el.style.setProperty('animation', 'none', 'important');
                });

                if (typeof elementorFrontend !== 'undefined' && elementorFrontend.elementsHandler) {
                    try {
                        elementorFrontend.elementsHandler.init();
                    } catch(e) {}
                }

                if (typeof elementorFrontend !== 'undefined' && elementorFrontend.utils) {
                    document.querySelectorAll(
                        '.elementor-element:not(.elementor-element-edit-mode)'
                    ).forEach(el => {
                        try {
                            const obs = new IntersectionObserver((entries) => {
                                entries.forEach(entry => {
                                    if (entry.isIntersecting) {
                                        entry.target.classList.remove('elementor-hidden',
                                            'elementor-screen-only');
                                        obs.unobserve(entry.target);
                                    }
                                });
                            }, { threshold: 0 });
                            obs.observe(el);
                        } catch(e) {}
                    });
                }

                document.querySelectorAll(
                    '[data-elementor-type="wp-post"], [data-elementor-type="wp-page"]'
                ).forEach(wrap => {
                    const sections = wrap.querySelectorAll(
                        '.elementor-section, .elementor-widget'
                    );
                    sections.forEach(el => {
                        el.classList.remove('elementor-invisible');
                        if (getComputedStyle(el).opacity === '0') {
                            el.style.setProperty('opacity', '1', 'important');
                            el.style.setProperty('visibility', 'visible', 'important');
                        }
                    });
                });
            }
        """)
    except Exception:
        pass

    try:
        step = 400
        dist = page.evaluate("() => Math.min(document.body.scrollHeight, 20000)")
        page.evaluate(f"""
            () => new Promise(resolve => {{
                let scrolled = 0;
                const timer = setInterval(() => {{
                    window.scrollBy(0, {step});
                    scrolled += {step};
                    if (scrolled >= {dist}) {{
                        clearInterval(timer);
                        window.scrollTo(0, 0);
                        resolve();
                    }}
                }}, 80);
                setTimeout(() => {{ clearInterval(timer); window.scrollTo(0, 0); resolve(); }}, 15000);
            }})
        """, timeout=20000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('.elementor-invisible').forEach(el => {
                    el.classList.remove('elementor-invisible');
                    el.style.setProperty('opacity', '1', 'important');
                    el.style.setProperty('visibility', 'visible', 'important');
                    el.style.setProperty('transform', 'none', 'important');
                });
            }
        """)
        page.wait_for_timeout(500)
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

def _inject_early_fixes(page):
    try:
        page.add_style_tag(content="""
            .elementor-invisible,
            .elementor-invisible.elementor-element,
            .elementor-widget.elementor-invisible {
                opacity: 1 !important;
                visibility: visible !important;
                transform: none !important;
                animation: none !important;
                transition: none !important;
                display: inherit !important;
            }
            .lazyload, .lazyloading {
                opacity: 1 !important;
            }
            .elementor-background-slideshow {
                min-height: 100vh !important;
            }
        """)
    except Exception:
        pass

def _navigate(page, url: str, retries: int = 2) -> Tuple[bool, str]:    
    for attempt in range(1 + retries):
        try:
            page.goto(url, wait_until='networkidle', timeout=60000)
            actual = page.url
            return True, actual
        except Exception:
            if attempt < retries:
                import time
                time.sleep(3 * (attempt + 1))
                continue
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                actual = page.url
                return True, actual
            except Exception as e:
                print(f"   [NAV ERR] {e}")
                return False, url

def _take_screenshot(page, output_path: Path):
    try:
        page_height = page.evaluate("() => document.body.scrollHeight")
    except Exception:
        page_height = 0

    if page_height > SCREENSHOT_MAX_HEIGHT:
        print(f"   [!] strona ma {page_height}px — przycinam do {SCREENSHOT_MAX_HEIGHT}px")
        try:
            page.screenshot(
                path=str(output_path),
                clip={'x': 0, 'y': 0, 'width': 1440, 'height': SCREENSHOT_MAX_HEIGHT}
            )
            return True
        except Exception as e:
            print(f"   [SHOT ERR clipped] {e}")
            return False
    else:
        try:
            page.screenshot(path=str(output_path), full_page=True)
            return True
        except Exception as e:
            print(f"   [SHOT ERR] {e}")
            return False

# ─── asset capture via network interception ───────────────────────────────────

def _make_response_handler(assets_dir: Path, captured: dict, fname_counts: dict, css_assets: dict):
    fallback_queue = []

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

            is_media_ct = any(t in content_type for t in (
                'image/', 'font/', 'text/css', 'javascript', 'audio/', 'video/'
            ))

            if (ext not in ASSET_EXTENSIONS
                    and rt not in ('stylesheet', 'script', 'image', 'font', 'media')
                    and not is_media_ct):
                return

            try:
                body = response.body()
            except Exception:
                fallback_queue.append(req_url)
                return

            if not body:
                return

            local_rel, abs_path = url_to_local_path(req_url, assets_dir, fname_counts, content_type)
            abs_path.write_bytes(body)
            captured[req_url] = local_rel

            if 'text/css' in content_type or ext == '.css':
                css_assets[req_url] = (abs_path, body)

            if response.url != req_url:
                captured[response.url] = local_rel
                if 'text/css' in content_type or ext == '.css':
                    css_assets[response.url] = (abs_path, body)

        except Exception:
            pass

    handle_response.fallback_queue = fallback_queue
    return handle_response

def _normalize_url_for_lookup(url: str) -> str:
    if url.startswith('http://'):
        return 'https://' + url[7:]
    return url


def _build_normalized_captured(captured: dict) -> dict:
    norm = {}
    for url, local in captured.items():
        norm[url] = local
        n = _normalize_url_for_lookup(url)
        if n not in norm:
            norm[n] = local
    return norm


def _rewrite_html(html: str, captured: dict, page_url: str) -> str:
    if not captured:
        return html

    norm_captured = _build_normalized_captured(captured)

    html = re.sub(r'<base\s+[^>]*?>', '', html, flags=re.IGNORECASE)

    attr_pat = re.compile(
        r'(?P<attr>(?:src|href|poster|data-src|data-lazy-src|data-bg|data-bg-url|'
        r'data-bg-image|data-retina|data-image)'
        r'\s*=\s*["\'])(?P<url>[^"\']+)(?P<end>["\'])',
        re.IGNORECASE
    )
    srcset_pat = re.compile(
        r'(?P<attr>(?:srcset|data-srcset|data-lazy-srcset)'
        r'\s*=\s*["\'])(?P<val>[^"\']+)(?P<end>["\'])',
        re.IGNORECASE
    )

    def _abs(u):
        try:
            return urljoin(page_url, u)
        except ValueError:
            return None

    def _lookup(a):
        if a and a in norm_captured:
            return norm_captured[a]
        if a:
            n = _normalize_url_for_lookup(a)
            if n in norm_captured:
                return norm_captured[n]
        return None

    def replacer(m):
        attr, u, end = m.group('attr'), m.group('url'), m.group('end')
        if u.startswith(('data:', 'blob:', '#', 'mailto:', 'tel:', 'javascript:')):
            return m.group(0)
        a = _abs(u)
        loc = _lookup(a)
        if loc:
            return attr + loc + end
        return m.group(0)

    def replacer_srcset(m):
        attr, val, end = m.group('attr'), m.group('val'), m.group('end')
        parts = []
        for part in val.split(','):
            tokens = part.strip().split()
            if tokens:
                a = _abs(tokens[0])
                loc = _lookup(a)
                if loc:
                    tokens[0] = loc
            parts.append(' '.join(tokens))
        return attr + ', '.join(parts) + end

    html = attr_pat.sub(replacer, html)
    html = srcset_pat.sub(replacer_srcset, html)

    for original in sorted(captured, key=len, reverse=True):
        local = captured[original]
        if original == local:
            continue
        esc = re.escape(original)
        html = re.sub(
            r'url\((["\'\']?)' + esc + r'(["\'\']?)\)',
            lambda m, loc=local: 'url(' + m.group(1) + loc + m.group(2) + ')',
            html, flags=re.IGNORECASE
        )
        norm_orig = _normalize_url_for_lookup(original)
        if norm_orig != original:
            esc_n = re.escape(norm_orig)
            html = re.sub(
                r'url\((["\'\']?)' + esc_n + r'(["\'\']?)\)',
                lambda m, loc=local: 'url(' + m.group(1) + loc + m.group(2) + ')',
                html, flags=re.IGNORECASE
            )

    _url_in_style = re.compile(
        r'url\(\s*(?:&quot;|["\'\'])?([^"\'\')&\s]+)(?:&quot;|["\'\'])?\s*\)',
        re.IGNORECASE
    )

    def _fix_style_url(m):
        ref = m.group(1)
        if ref.startswith(('data:', 'blob:', '#')):
            return m.group(0)
        a = _abs(ref)
        loc = _lookup(a)
        if loc:
            return 'url("' + loc + '")'
        return m.group(0)

    def _fix_style_attr(m):
        return m.group('pre') + _url_in_style.sub(_fix_style_url, m.group('val')) + m.group('post')

    html = re.sub(
        r'(?P<pre>style=")(?P<val>[^"]*)(?P<post>")',
        _fix_style_attr, html, flags=re.IGNORECASE
    )
    html = re.sub(
        r"(?P<pre>style=')(?P<val>[^']*)(?P<post>')",
        _fix_style_attr, html, flags=re.IGNORECASE
    )

    return html

def _rewrite_single_css(css_text: str, css_url: str, captured: dict) -> tuple:
    url_pat = re.compile(r'url\(\s*(["\']?)([^\"\')\ s]+)\1\s*\)', re.IGNORECASE)
    imp_pat = re.compile(r'(@import\s+)(["\'])([^\"\']+)\2', re.IGNORECASE)
    changed = False

    def _local(ref):
        if ref.startswith(('data:', 'blob:', '#', 'javascript:')):
            return None
        try:
            absolute = urljoin(css_url, ref)
        except ValueError:
            return None
        return captured[absolute].split('/')[-1] if absolute in captured else None

    def repl_url(m):
        nonlocal changed
        q, ref = m.group(1), m.group(2)
        loc = _local(ref)
        if loc:
            changed = True
            return f'url({q}{loc}{q})'
        return m.group(0)

    def repl_import(m):
        nonlocal changed
        prefix, q, ref = m.group(1), m.group(2), m.group(3)
        loc = _local(ref)
        if loc:
            changed = True
            return f'{prefix}{q}{loc}{q}'
        return m.group(0)

    css_text = url_pat.sub(repl_url, css_text)
    css_text = imp_pat.sub(repl_import, css_text)
    return css_text, changed

def _rewrite_css_assets(css_assets: dict, captured: dict):
    for css_url, (abs_path, original_body) in css_assets.items():
        try:
            css_text = original_body.decode('utf-8', errors='replace')
            new_css, changed = _rewrite_single_css(css_text, css_url, captured)
            if changed:
                abs_path.write_text(new_css, encoding='utf-8', errors='replace')
        except Exception:
            pass

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
                    } catch (e) {}
                }
                const elements = document.querySelectorAll('[style*="blob:"]');
                elements.forEach(el => {
                    let style = el.getAttribute('style');
                    style = style.replace(/url\\(["']?blob:[^"')]+["']?\\)/g, 'url(none)');
                    el.setAttribute('style', style);
                });
            }
        """)
    except Exception:
        pass

def _fetch_missing_css_assets(css_assets: dict, captured: dict, assets_dir: Path, fname_counts: dict, session: requests.Session):
    url_pattern = re.compile(r'url\(\s*["\']?([^"\')\s]+)["\']?\s*\)', re.IGNORECASE)
    import_pattern_css = re.compile(r'@import\s+["\']([^"\']+)["\']', re.IGNORECASE)

    queue = list(css_assets.keys())
    visited_css = set(queue)
    max_depth = 3

    while queue and max_depth > 0:
        max_depth -= 1
        css_url = queue.pop(0)
        entry = css_assets.get(css_url)
        if entry is None:
            continue
        abs_path, body = entry

        try:
            css_text = body.decode('utf-8', errors='replace')
        except Exception:
            continue

        refs = [m.group(1) for m in url_pattern.finditer(css_text)]
        refs += [m.group(1) for m in import_pattern_css.finditer(css_text)]

        for ref in refs:
            if ref.startswith(('data:', 'blob:', '#')):
                continue
            try:
                absolute = urljoin(css_url, ref)
            except ValueError:
                continue
            if absolute in captured:
                continue
            try:
                r = session.get(absolute, timeout=15)
                if r.status_code < 200 or r.status_code >= 400 or not r.content:
                    continue
                content_type = r.headers.get('content-type', '').lower()
                local_rel, local_abs = url_to_local_path(absolute, assets_dir, fname_counts, content_type)
                local_abs.write_bytes(r.content)
                captured[absolute] = local_rel
                if 'text/css' in content_type or absolute.lower().endswith('.css'):
                    if absolute not in visited_css:
                        visited_css.add(absolute)
                        css_assets[absolute] = (local_abs, r.content)
                        queue.append(absolute)
            except Exception:
                pass

# ─── process functions ────────────────────────────────────────────────────────

def process_full(page_url: str, context, output_dir: Path, aggressive: bool = False,
                 progress: str = '') -> tuple:
    assets_dir = output_dir / 'assets'
    assets_dir.mkdir(parents=True, exist_ok=True)

    captured = {}
    fname_counts = {}
    css_assets = {}

    session = requests.Session()
    session.headers['User-Agent'] = NORMAL_USER_AGENT

    _set_consent_cookies(context, page_url)
    page = context.new_page()
    handler = _make_response_handler(assets_dir, captured, fname_counts, css_assets)
    page.on('response', handler)

    ok, actual_url = _navigate(page, page_url)
    if not ok:
        page.close()
        return False, False

    _inject_early_fixes(page)

    if actual_url != page_url:
        print(f"   → redirect: {actual_url}")
    else:
        print(f"   → {actual_url}")

    _do_cleanup(page, aggressive)
    _scroll_and_wait(page)

    _force_lazy_load(page)
    _force_slider_render(page)
    _force_sr7_render(page)
    _force_revslider_render(page)
    _force_carousel_load_aggressive(page)

    _do_cleanup(page, aggressive)
    _force_lazy_load(page)

    _wait_for_images(page)
    _wait_for_fonts(page)
    _disable_css_animations(page)
    _force_elementor_render(page)

    try:
        page.evaluate("""
            () => {
                document.querySelectorAll(
                    '.flickity-page-dots .dot, .owl-dot, .slick-dots li'
                ).forEach(dot => dot.click());
            }
        """)
        page.wait_for_timeout(2000)
        _wait_for_images(page, timeout=5000)
    except Exception:
        pass

    try:
        page.wait_for_load_state('networkidle', timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    _convert_blobs_to_base64(page)

    for fallback_url in handler.fallback_queue:
        if fallback_url in captured:
            continue
        try:
            r = session.get(fallback_url, timeout=15)
            if r.status_code == 200 and r.content:
                ct = r.headers.get('content-type', '').lower()
                local_rel, local_abs = url_to_local_path(fallback_url, assets_dir, fname_counts, ct)
                local_abs.write_bytes(r.content)
                captured[fallback_url] = local_rel
                if 'text/css' in ct or urlparse(fallback_url).path.lower().endswith('.css'):
                    css_assets[fallback_url] = (local_abs, r.content)
        except Exception:
            pass

    html_ok = False
    try:
        html = page.content()
        html = _rewrite_html(html, captured, page_url)
        (output_dir / 'index.html').write_text(html, encoding='utf-8', errors='replace')
        _fetch_missing_css_assets(css_assets, captured, assets_dir, fname_counts, session)
        _rewrite_css_assets(css_assets, captured)

        try:
            extra_images = page.evaluate("""
                () => {
                    const urls = new Set();
                    const addUrl = (u) => {
                        if (!u) return;
                        if (u.startsWith('//')) u = 'https:' + u;
                        if (u.startsWith('http')) urls.add(u);
                    };
                    document.querySelectorAll('[srcset]').forEach(el => {
                        (el.getAttribute('srcset') || '').split(',').forEach(part => {
                            addUrl(part.trim().split(' ')[0]);
                        });
                    });
                    document.querySelectorAll('[data-srcset], [data-lazy-srcset]').forEach(el => {
                        let srcset = el.getAttribute('data-srcset') || el.getAttribute('data-lazy-srcset');
                        if (srcset) {
                            srcset.split(',').forEach(part => {
                                addUrl(part.trim().split(' ')[0]);
                            });
                        }
                    });
                    document.querySelectorAll('[data-bg], [data-lazy-bg], [data-bg-url]').forEach(el => {
                        addUrl(el.getAttribute('data-bg') || el.getAttribute('data-lazy-bg') || el.getAttribute('data-bg-url'));
                    });
                    document.querySelectorAll('img[src^="http"]').forEach(img => {
                        addUrl(img.getAttribute('src'));
                    });
                    document.querySelectorAll('[style*="background-image"]').forEach(el => {
                        const style = el.getAttribute('style') || '';
                        const m = style.match(/url\\(['"]?([^'")]+)['"]?\\)/g);
                        if (m) m.forEach(match => {
                            const u = match.replace(/url\\(['"]?/, '').replace(/['"]?\\)/, '');
                            addUrl(u);
                        });
                    });
                    document.querySelectorAll('[data-settings]').forEach(el => {
                        try {
                            const raw = el.getAttribute('data-settings');
                            if (!raw) return;
                            const decoded = raw.replace(/&quot;/g, '"').replace(/&amp;/g, '&');
                            const data = JSON.parse(decoded);
                            const extract = (obj) => {
                                if (typeof obj === 'string' && (obj.includes('.png') || obj.includes('.jpg') || obj.includes('.jpeg') || obj.includes('.gif') || obj.includes('.webp') || obj.includes('.svg') || obj.includes('.avif'))) {
                                    addUrl(obj);
                                }
                                if (obj && typeof obj === 'object') {
                                    if (Array.isArray(obj)) obj.forEach(extract);
                                    else Object.values(obj).forEach(extract);
                                }
                            };
                            extract(data);
                        } catch(e) {}
                    });
                    document.querySelectorAll('.elementor-background-slideshow__slide__image').forEach(el => {
                        const bg = getComputedStyle(el).backgroundImage;
                        if (bg && bg !== 'none') {
                            const m = bg.match(/url\\(["']?(.+?)["']?\\)/);
                            if (m) addUrl(m[1]);
                        }
                    });
                    return Array.from(urls);
                }
            """)
            for img_url in extra_images:
                nurl = _normalize_url_for_lookup(img_url)
                if nurl not in captured and img_url not in captured:
                    for try_url in (nurl, img_url):
                        if try_url in captured:
                            break
                        try:
                            r = session.get(try_url, timeout=10)
                            if r.status_code == 200 and r.content:
                                local_rel, local_abs = url_to_local_path(
                                    try_url, assets_dir, fname_counts,
                                    r.headers.get('content-type', '')
                                )
                                local_abs.write_bytes(r.content)
                                captured[try_url] = local_rel
                                if try_url != img_url:
                                    captured[img_url] = local_rel
                                break
                        except Exception:
                            pass
        except Exception as e:
            print(f"   extra images warning: {e}")

        try:
            html = _rewrite_html(html, captured, page_url)
            (output_dir / 'index.html').write_text(html, encoding='utf-8', errors='replace')
        except Exception:
            pass

        unique_assets = len(set(captured.values()))
        print(f"   assets: {unique_assets} files saved")
        html_ok = True
    except Exception as e:
        print(f"   [HTML ERR] {e}")

    shot_ok = _take_screenshot(page, output_dir / 'screenshot_full.png')

    page.close()
    return html_ok, shot_ok

def process_screenshot_only(page_url: str, context, output_path: Path,
                            aggressive: bool = False, progress: str = '') -> bool:
    _set_consent_cookies(context, page_url)
    page = context.new_page()

    ok, actual_url = _navigate(page, page_url)
    if not ok:
        page.close()
        return False

    _inject_early_fixes(page)

    if actual_url != page_url:
        print(f"   → redirect: {actual_url}")
    else:
        print(f"   → {actual_url}")

    _do_cleanup(page, aggressive)
    _scroll_and_wait(page)

    _force_lazy_load(page)
    _force_slider_render(page)
    _force_sr7_render(page)
    _force_revslider_render(page)
    _force_carousel_load_aggressive(page)
    _do_cleanup(page, aggressive)
    _force_lazy_load(page)
    _wait_for_images(page)
    _wait_for_fonts(page)
    _disable_css_animations(page)
    _force_elementor_render(page)

    try:
        page.evaluate("""
            () => {
                document.querySelectorAll(
                    '.flickity-page-dots .dot, .owl-dot, .slick-dots li'
                ).forEach(dot => dot.click());
            }
        """)
        page.wait_for_timeout(2000)
        _wait_for_images(page, timeout=5000)
    except Exception:
        pass

    try:
        page.wait_for_load_state('networkidle', timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    shot_ok = _take_screenshot(page, output_path)
    if shot_ok:
        try:
            kb = output_path.stat().st_size // 1024
            print(f"   saved  {output_path.name}  ({kb} KB)")
        except Exception:
            pass

    page.close()
    return shot_ok

# ─── zip helpers ──────────────────────────────────────────────────────────────

SKIP_DIRS = {'__pycache__', '.git', '.svn', '.hg', 'node_modules', '.DS_Store', '.tox', '.venv', 'venv', '.mypy_cache'}

def pack_dir_to_zip(src_dir: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob('*'):
            if f.is_file() and not any(part in SKIP_DIRS for part in f.parts):
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
    normalized = [
        u if u.startswith(('http://', 'https://')) else 'https://' + u
        for u in urls
    ]

    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except ImportError:
        print("[!] Playwright not installed.")
        sys.exit(1)

    try:
        _run_inner(browser, normalized, base_output, mode, keep_folders)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass

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

def _run_inner(browser, normalized, base_output, mode, keep_folders):
    aggressive = mode.startswith('clean-')
    effective = mode.replace('clean-', '', 1)
    mode_label = f"CLEAN + {effective.upper()}" if aggressive else effective.upper()
    total_pages = len(normalized)
    logging.info(f"mode={mode_label} pages={total_pages} output={base_output}")

    if effective == 'screenshots':
        print(f"\n  mode  : {mode_label}")
        print(f"  pages : {total_pages}\n")

        by_domain = defaultdict(list)
        for url in normalized:
            by_domain[get_domain(url)].append(url)

        tmp_dir = base_output / '_screenshots_tmp'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ok_count = fail_count = 0
        page_counter = 0

        for domain, domain_urls in by_domain.items():
            print(f"\n  [*] {domain}  ({len(domain_urls)} pages)")
            domain_shots = []

            for url in domain_urls:
                page_counter += 1
                progress = f"[{page_counter}/{total_pages}]"
                fname = get_screenshot_filename(url)
                out_path = tmp_dir / fname
                print(f"\n  {progress} {url}")
                logging.info(f"[{page_counter}/{total_pages}] screenshot {url}")
                ctx = browser.new_context(
                    viewport={'width': 1440, 'height': 900},
                    bypass_csp=True,
                    user_agent=NORMAL_USER_AGENT
                )
                success = process_screenshot_only(url, ctx, out_path, aggressive=aggressive, progress=progress)
                ctx.close()
                if success:
                    domain_shots.append(out_path)
                    ok_count += 1
                else:
                    fail_count += 1
                    print(f"   [FAIL]")
                    logging.error(f"[FAIL] screenshot {url}")

            if domain_shots:
                zip_path = base_output / get_zip_name(domain, mode='screenshots')
                pack_files_to_zip(domain_shots, zip_path)

        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        print(f"\n  done  : {ok_count} ok  /  {fail_count} failed")
        logging.info(f"done: {ok_count} ok, {fail_count} failed")
        return

    is_crawl = effective == 'crawl'

    by_domain = defaultdict(list)
    for url in normalized:
        by_domain[get_domain(url)].append(url)

    print(f"\n  mode    : {mode_label}")
    print(f"  domains : {len(by_domain)}")
    print(f"  pages   : {total_pages}\n")

    page_counter = 0

    for domain, domain_urls in by_domain.items():
        zip_path = base_output / get_zip_name(domain, mode='crawl' if is_crawl else 'full')
        domain_tmp = base_output / sanitize_name(domain)
        domain_tmp.mkdir(parents=True, exist_ok=True)

        print(f"\n  [*] {domain}  ({len(domain_urls)} pages)")
        logging.info(f"domain={domain} pages={len(domain_urls)}")

        for url in domain_urls:
            page_counter += 1
            progress = f"[{page_counter}/{total_pages}]"
            sub = get_subfolder_name(url)
            page_dir = domain_tmp / sub
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / 'meta.txt').write_text(
                f"URL: {url}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
                encoding='utf-8'
            )
            print(f"\n  {progress} {url}")
            print(f"      -> {sub}/")
            logging.info(f"[{page_counter}/{total_pages}] {url} -> {sub}/")

            ctx = browser.new_context(
                viewport={'width': 1440, 'height': 900},
                bypass_csp=True,
                user_agent=NORMAL_USER_AGENT
            )
            html_ok, shot_ok = process_full(url, ctx, page_dir, aggressive=aggressive, progress=progress)
            ctx.close()

            status = '[OK]' if (html_ok or shot_ok) else '[FAIL]'
            print(f"   {status}")
            logging.info(f"{status} html={html_ok} shot={shot_ok}")

        pack_dir_to_zip(domain_tmp, zip_path)
        if not keep_folders:
            shutil.rmtree(domain_tmp)

# ─── interactive prompt ───────────────────────────────────────────────────────

def prompt_mode() -> tuple:
    print("  select mode:")
    print()
    print("    [1]  full              HTML + assets + screenshots")
    print("    [2]  screenshots       screenshots only  (fast)")
    print("    [3]  crawl             auto-discover pages from sitemap + links")
    print("    [4]  clean             aggressive popup nuke, then choose ↓")
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
        if choice in ('3', 'crawl'):
            return 'crawl', False
        if choice in ('4', 'clean'):
            print()
            print("  clean mode — after nuking popups:")
            print()
            print("    [1]  full          HTML + assets + screenshots")
            print("    [2]  screenshots   screenshots only")
            print("    [3]  crawl         auto-discover pages")
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
                if sub in ('3', 'crawl'):
                    return 'crawl', True
                print("  [?] type 1, 2 or 3")
        print("  [?] type 1, 2, 3 or 4")

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

    VALID_MODES = ('full', 'screenshots', 'crawl', 'clean-full', 'clean-screenshots', 'clean-crawl')

    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description='snap.py — web snapshot tool')
        parser.add_argument('urls', nargs='*')
        parser.add_argument('-f', '--file')
        parser.add_argument('-o', '--output', default='./results')
        parser.add_argument('--mode', choices=VALID_MODES, default='full')
        parser.add_argument('--keep-folders', action='store_true')
        parser.add_argument('--max-pages', type=int, default=50, help='Max pages for crawl mode')
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

        effective = args.mode.replace('clean-', '', 1)

        if effective == 'crawl':
            if not urls:
                print("[!] Provide at least one URL to crawl from.")
                sys.exit(1)
            session = requests.Session()
            session.headers['User-Agent'] = NORMAL_USER_AGENT
            print(f"\n  [*] discovering URLs...")
            all_crawl_urls = []
            for seed_url in urls:
                seed_url = seed_url if seed_url.startswith(('http://', 'https://')) else 'https://' + seed_url
                print(f"      sitemap + crawl: {seed_url}")
                sm_urls = fetch_sitemap_urls(seed_url, session)
                cr_urls = crawl_internal_links(seed_url, session, max_pages=args.max_pages)
                combined = list(dict.fromkeys(sm_urls + cr_urls))
                print(f"        sitemap: {len(sm_urls)}, crawl: {len(cr_urls)}, total: {len(combined)}")
                all_crawl_urls.extend(combined)
            urls = list(dict.fromkeys(all_crawl_urls))

        if not urls:
            print("[!] No URLs found.")
            sys.exit(1)
        seen = set()
        unique = [u for u in urls if not (u in seen or seen.add(u))]
        out = Path(args.output).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        log_path = setup_logging(out)
        print(f"  log: {log_path}")
        run(unique, out, mode=args.mode, keep_folders=args.keep_folders)
        return

    effective, aggressive = prompt_mode()
    mode = f"clean-{effective}" if aggressive else effective
    urls = prompt_urls()

    if effective == 'crawl':
        if not urls:
            print("[!] Provide at least one seed URL.")
            sys.exit(0)
        session = requests.Session()
        session.headers['User-Agent'] = NORMAL_USER_AGENT
        print(f"\n  [*] discovering URLs...")
        all_crawl_urls = []
        for seed_url in urls:
            seed_url = seed_url if seed_url.startswith(('http://', 'https://')) else 'https://' + seed_url
            print(f"      sitemap + crawl: {seed_url}")
            sm_urls = fetch_sitemap_urls(seed_url, session)
            cr_urls = crawl_internal_links(seed_url, session, max_pages=50)
            combined = list(dict.fromkeys(sm_urls + cr_urls))
            print(f"        sitemap: {len(sm_urls)}, crawl: {len(cr_urls)}, total: {len(combined)}")
            all_crawl_urls.extend(combined)
        urls = list(dict.fromkeys(all_crawl_urls))

    out = prompt_output()

    seen = set()
    unique = [u for u in urls if not (u in seen or seen.add(u))]

    mode_label = f"CLEAN + {effective.upper()}" if aggressive else effective.upper()

    print(f"\n  ── starting {'─'*35}")
    print(f"  mode   : {mode_label}")
    print(f"  pages  : {len(unique)}")
    print(f"  output : {out.resolve()}")
    print(f"  {'─'*44}\n")

    log_path = setup_logging(out)
    print(f"  log: {log_path}")

    run(unique, out, mode=mode)

if __name__ == '__main__':
    main()