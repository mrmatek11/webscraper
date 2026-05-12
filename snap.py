#!/usr/bin/env python3
"""
snap.py — Web Snapshot Tool v4 (hybryda + reset animation strategy)

KLUCZOWE ZMIANY vs v3:
  #A  add_init_script() przed nawigacją — globalny CSS killer animacji +
      IntersectionObserver hijack + localStorage consent flags.
      Zastępuje większość _force_*_render funkcji.
  #B  Architektura: ONE browser per THREAD (nie per run).
      v4.0 używał jednego browsera dla wszystkich wątków — Playwright sync API
      jest greenlet-bound i crash'uje przy ThreadPoolExecutor.
      v4.1: każdy wątek tworzy własny playwright+browser via _thread_local.
  #C  Rozszerzony lazy loader: data-lazy-load-src, data-lazy-background-image,
      data-background-image, data-bg-image + parsowanie data-ww_rwd (Webwave).
  #D  _finish_all_animations: document.getAnimations().finish() + GSAP +
      WOW + AOS + anime.js w JEDNEJ funkcji.
  #E  Lepszy cookie killer: Webwave cookiePopup, localStorage flags,
      "Allow All" button auto-click w wielu językach.
  #F  _wait_for_images: sprawdza naturalWidth > 0 (nie tylko complete).
  #G  Slider walkthrough: przeklikuje wszystkie dots dla Slick/Webwave/Owl/Swiper.
  #H  Route blocking: analytics/tracking blokowane dla szybkości.
  #I  Diagnostyka na końcu: zlicza puste/niewidoczne elementy → log.
  #J  SCREENSHOT_MAX_HEIGHT przeniesione do _CFG (thread-safe).

Z v3 zachowane:
  - cały popup-killing (_inject_anti_popup_css, close_popups itd.)
  - sitemap/crawl
  - rewriting HTML/CSS
  - asset capture przez response handler
  - blob → base64
"""

import argparse
import configparser
import logging
import re
import shutil
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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
  [ web snapshot tool v4.1 ]
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

_log_file = None
_log_handler = None

# ─── konfiguracja ─────────────────────────────────────────────────────────────

_CONFIG_DEFAULTS = {
    'performance': {'workers': '1', 'block_analytics': 'true'},
    'browser': {
        'viewport_width':        '1440',
        'viewport_height':       '900',
        'max_screenshot_height': '15000',
    },
    'crawl': {'max_pages': '50'},
}

_CFG = {}


def load_config(cfg_path=None):
    global _CFG

    parser = configparser.ConfigParser()
    for section, values in _CONFIG_DEFAULTS.items():
        parser[section] = values

    search_paths = [
        cfg_path,
        Path('snap.cfg'),
        Path(__file__).parent / 'snap.cfg',
    ]
    loaded_from = None
    for p in search_paths:
        if p is not None and Path(p).exists():
            parser.read(p, encoding='utf-8')
            loaded_from = Path(p)
            break

    _CFG = {
        'workers':               parser.getint('performance', 'workers'),
        'block_analytics':       parser.getboolean('performance', 'block_analytics', fallback=True),
        'viewport_width':        parser.getint('browser',     'viewport_width'),
        'viewport_height':       parser.getint('browser',     'viewport_height'),
        'max_screenshot_height': parser.getint('browser',     'max_screenshot_height'),
        'max_pages':             parser.getint('crawl',       'max_pages'),
    }

    if loaded_from:
        print(f"  [cfg] wczytano: {loaded_from.resolve()}  (workers={_CFG['workers']}, "
              f"block_analytics={_CFG['block_analytics']})")
    else:
        print(f"  [cfg] snap.cfg nie znaleziony — defaults  (workers={_CFG['workers']})")

    return _CFG


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


# ─── #A: INIT SCRIPT — wstrzykiwany PRZED każdym goto() ───────────────────────

_INIT_SCRIPT = r"""
(() => {
    // ─── 1) GLOBALNY CSS — animacje 0.001s, transitions 0.001s ──────────
    const css = `
        *, *::before, *::after {
            animation-duration: 0.001s !important;
            animation-delay: 0s !important;
            transition-duration: 0.001s !important;
            transition-delay: 0s !important;
            animation-iteration-count: 1 !important;
        }
        /* WOW.js / animate.css — wymuś widoczność */
        .wow, [class*="animate__"], [data-aos] {
            visibility: visible !important;
            opacity: 1 !important;
            transform: none !important;
            animation-name: none !important;
        }
        /* Elementor invisible */
        .elementor-invisible {
            opacity: 1 !important;
            visibility: visible !important;
            transform: none !important;
        }
        /* Preloadery — natychmiast hide */
        [class*="preloader"], [id*="preloader"],
        [class*="page-loader"], [id*="page-loader"],
        [class*="loading-screen"], [id*="loading-screen"],
        .rs-loader, .tp-loader, .sr7-loader,
        #cookiePopupHTMLAppContainer { display: none !important; }
        /* Webwave cookie popup */
        [id*="cookiePopup"], [class*="cookiePopup"],
        #cookiesEU-box, .ww_cookie_info { display: none !important; }
    `;
    const installStyle = () => {
        if (document.getElementById('__snap_init_style__')) return;
        const s = document.createElement('style');
        s.id = '__snap_init_style__';
        s.textContent = css;
        (document.head || document.documentElement).appendChild(s);
    };
    installStyle();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', installStyle);
    }

    // ─── 2) IntersectionObserver HIJACK ──────────────────────────────────
    try {
        const RealIO = window.IntersectionObserver;
        if (RealIO) {
            window.IntersectionObserver = class FakeIO {
                constructor(cb, opts) {
                    this.cb = cb;
                    this.opts = opts || {};
                    this._observed = new Set();
                }
                observe(el) {
                    if (!el || this._observed.has(el)) return;
                    this._observed.add(el);
                    const fire = () => {
                        try {
                            const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : {};
                            this.cb([{
                                isIntersecting: true,
                                intersectionRatio: 1,
                                target: el,
                                boundingClientRect: rect,
                                intersectionRect: rect,
                                rootBounds: null,
                                time: performance.now(),
                            }], this);
                        } catch(e) {}
                    };
                    setTimeout(fire, 0);
                    setTimeout(fire, 200);
                }
                unobserve(el) { this._observed.delete(el); }
                disconnect() { this._observed.clear(); }
                takeRecords() { return []; }
            };
        }
    } catch(e) {}

    // ─── 3) Cookie consent flags w storage ────────────────────────────────
    try {
        const consent = {
            'cookieSettings': JSON.stringify({
                acceptedAll: true,
                acceptedTime: Date.now(),
                marketing: true, statistics: true, preferences: true, functional: true,
            }),
            'webwave-cookie-consent': 'accepted-all',
            'CookieConsent': '{stamp:%27snap%27%2Cnecessary:true%2Cpreferences:true%2Cstatistics:true%2Cmarketing:true%2Cver:1}',
            'OptanonAlertBoxClosed': new Date().toISOString(),
            'OptanonConsent': 'isGpcEnabled=0&datestamp=' + encodeURIComponent(new Date().toString()) + '&groups=C0001:1,C0002:1,C0003:1,C0004:1',
            'cookieconsent_status': 'allow',
            'cookies_accepted': 'true',
            'cookie_accepted': 'true',
            'gdpr_consent': 'true',
            'cc_cookie_accept': 'true',
            'cookiehub': '{"answered":true,"approved":["necessary","analytics","marketing","preferences"]}',
            'klaro': 'true',
            'borlabs-cookie': '{"consents":{"essential":["borlabs-cookie"]},"version":3}',
            '_iub_cs-s1234567': 'true',
        };
        for (const [k, v] of Object.entries(consent)) {
            try { localStorage.setItem(k, v); } catch(e) {}
            try { sessionStorage.setItem(k, v); } catch(e) {}
        }
    } catch(e) {}

    // ─── 4) prefers-reduced-motion: reduce ───────────────────────────────
    try {
        const origMM = window.matchMedia;
        window.matchMedia = function(q) {
            if (typeof q === 'string' && q.indexOf('prefers-reduced-motion') >= 0) {
                return {
                    matches: q.indexOf('reduce') >= 0,
                    media: q,
                    onchange: null,
                    addListener: () => {}, removeListener: () => {},
                    addEventListener: () => {}, removeEventListener: () => {},
                    dispatchEvent: () => false,
                };
            }
            return origMM.call(window, q);
        };
    } catch(e) {}
})();
"""


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
        if fp.scheme not in ('http', 'https'):
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
    path_part = parsed.path.rstrip('/').split('?')[0]
    base = Path(path_part).name or 'asset'
    base = sanitize_name(base) or 'asset'

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

# ─── popup killing ─────────────────────────────────────────────────────────────

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
                    [id*="cookiePopup"], [class*="cookiePopup"],
                    [id*="fancybox-container"], [class*="fancybox-container"],
                    [id*="mfp-popup"], [class*="mfp-wrap"],
                    [class*="age-gate"], [id*="age-gate"],
                    [class*="exit-intent"], [id*="exit-intent"],
                    [class*="push-notification"], [id*="push-notification"],
                    .ww_cookie_info, #cookiesEU-box,
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
        '[id*="cookiePopup"] button:first-of-type',
        '.cookiePopup__button--accept', '.cookiePopup__acceptButton',
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
                    page.wait_for_timeout(300)
        except Exception:
            pass

    accept_texts = [
        'Allow All', 'Accept All', 'Accept all', 'Akceptuj wszystkie',
        'Zezwól na wszystkie', 'Zaakceptuj wszystkie', 'Zaakceptuj',
        'Zgadzam się', 'Rozumiem', 'OK', 'Got it', 'I agree',
        'Allow all cookies', 'Akceptuj', 'Zezwól',
    ]
    for text in accept_texts:
        try:
            btn = page.get_by_role('button', name=text, exact=False).first
            if btn and btn.is_visible(timeout=200):
                btn.click(timeout=1000)
                page.wait_for_timeout(300)
                break
        except Exception:
            pass

    for _ in range(3):
        try:
            page.keyboard.press('Escape')
            page.wait_for_timeout(150)
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
                    '[id*="cookie-banner"], [id*="cookiebar"], [id*="cookie-notice"], ' +
                    '[id*="cookiePopup"], .ww_cookie_info, #cookiesEU-box'
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
        page.wait_for_timeout(300)
    except Exception:
        pass

def close_popups_aggressive(page):
    inject_anti_popup_css(page)
    for attempt in range(4):
        close_popups(page)
        if attempt < 3:
            page.wait_for_timeout(1000)

# ─── #C: rozszerzony lazy loader ──────────────────────────────────────────────

def _force_lazy_load(page):
    try:
        page.evaluate(r"""
            () => {
                const SRC_ATTRS = [
                    'data-lazy-src', 'data-src', 'data-original',
                    'data-lazy-load-src',
                    'data-img-src',
                    'data-echo',
                    'data-srcdefer',
                ];
                const SRCSET_ATTRS = [
                    'data-srcset', 'data-lazy-srcset',
                ];
                const BG_ATTRS = [
                    'data-bg', 'data-lazy-bg', 'data-bg-url', 'data-bg-image',
                    'data-background-image',
                    'data-lazy-background-image',
                    'data-background',
                ];

                document.querySelectorAll('img').forEach(img => {
                    let src = null, srcset = null;
                    for (const a of SRC_ATTRS) {
                        const v = img.getAttribute(a);
                        if (v) { src = v; break; }
                    }
                    for (const a of SRCSET_ATTRS) {
                        const v = img.getAttribute(a);
                        if (v) { srcset = v; break; }
                    }
                    if (src) { try { img.src = src; } catch(e) {} }
                    if (srcset) { try { img.srcset = srcset; } catch(e) {} }
                    if (img.loading === 'lazy') img.loading = 'eager';
                    if (img.decoding === 'async') img.decoding = 'auto';
                    img.classList.remove('lazyload', 'lazyloading');
                    img.classList.add('lazyloaded');
                    if (img.src && !img.complete) {
                        const origSrc = img.src;
                        img.src = '';
                        img.src = origSrc;
                    }
                });

                document.querySelectorAll('source').forEach(source => {
                    for (const a of SRCSET_ATTRS) {
                        const v = source.getAttribute(a);
                        if (v) { try { source.srcset = v; } catch(e) {} break; }
                    }
                });

                BG_ATTRS.forEach(attr => {
                    document.querySelectorAll('[' + attr + ']').forEach(el => {
                        const v = el.getAttribute(attr);
                        if (v && !el.style.backgroundImage) {
                            el.style.backgroundImage = 'url("' + v + '")';
                        }
                    });
                });

                document.querySelectorAll('[data-ww_rwd]').forEach(el => {
                    try {
                        const raw = el.getAttribute('data-ww_rwd');
                        if (!raw) return;
                        const decoded = raw
                            .replace(/&quot;/g, '"')
                            .replace(/&amp;/g, '&');
                        const data = JSON.parse(decoded);
                        const pickMode = (obj) => {
                            if (!obj || typeof obj !== 'object') return null;
                            return obj.rwdMode_1 || obj.rwdMode_2 || obj.rwdMode_3 || obj.rwdMode_4
                                   || Object.values(obj)[0];
                        };
                        if (data['data-lazy-load-src']) {
                            const v = pickMode(data['data-lazy-load-src']);
                            if (v && el.tagName === 'IMG') {
                                try { el.src = v; } catch(e) {}
                                el.setAttribute('data-lazy-load-src', v);
                            }
                        }
                        if (data['data-lazy-background-image']) {
                            const v = pickMode(data['data-lazy-background-image']);
                            if (v) {
                                el.style.backgroundImage = 'url("' + v + '")';
                            }
                        }
                    } catch(e) {}
                });

                document.querySelectorAll('figure script[type="application/json"]').forEach(s => {
                    try {
                        const data = JSON.parse(s.textContent);
                        if (data.rwdProperties) {
                            const m1 = data.rwdProperties.rwdMode_1;
                            if (m1 && m1.imageSrc) {
                                const figure = s.closest('figure');
                                const slide = figure ? figure.closest('.gv_panel, .galleryList, .slick-slide') : null;
                                if (slide) {
                                    const img = slide.querySelector('img.gv_img, img');
                                    if (img && (!img.src || img.src.startsWith('data:'))) {
                                        try { img.src = m1.imageSrc; } catch(e) {}
                                    }
                                }
                            }
                        }
                    } catch(e) {}
                });

                document.querySelectorAll('img.lozad, [data-loaded="false"]').forEach(el => {
                    el.setAttribute('data-loaded', 'true');
                    el.classList.add('lazyloaded');
                });

                // ─── Swiper lazy images ──────────────────────────────────
                document.querySelectorAll('img.swiper-lazy').forEach(img => {
                    const src = img.getAttribute('data-src');
                    if (src) {
                        try { img.src = src; } catch(e) {}
                    }
                    const srcset = img.getAttribute('data-srcset');
                    if (srcset) {
                        try { img.srcset = srcset; } catch(e) {}
                    }
                    if (img.loading === 'lazy') img.loading = 'eager';
                    img.classList.remove('swiper-lazy');
                    img.classList.add('swiper-lazy-loaded');
                });

                document.querySelectorAll('.swiper-lazy[data-background], .swiper-lazy[data-bg]').forEach(el => {
                    const bg = el.getAttribute('data-background') || el.getAttribute('data-bg');
                    if (bg && !el.style.backgroundImage) {
                        el.style.backgroundImage = 'url("' + bg + '")';
                    }
                    el.classList.remove('swiper-lazy');
                    el.classList.add('swiper-lazy-loaded');
                });

                document.querySelectorAll('.elementor-widget-container .swiper-slide img').forEach(img => {
                    const src = img.getAttribute('data-src') || img.getAttribute('data-lazy-src');
                    if (src && (!img.src || img.src === '' || img.naturalWidth === 0)) {
                        try { img.src = src; } catch(e) {}
                    }
                    if (img.loading === 'lazy') img.loading = 'eager';
                });
            }
        """)
        page.wait_for_timeout(500)
    except Exception as e:
        logging.warning(f"_force_lazy_load: {e}")


# ─── #D: kombo killer animacji ────────────────────────────────────────────────

def _finish_all_animations(page):
    try:
        page.evaluate("""
            () => {
                try {
                    if (document.getAnimations) {
                        document.getAnimations().forEach(a => {
                            try { a.finish(); } catch(e) {}
                        });
                    }
                } catch(e) {}

                try {
                    if (window.gsap && gsap.globalTimeline) {
                        gsap.globalTimeline.getChildren(true, true, true).forEach(t => {
                            try { t.progress(1).pause(); } catch(e) {}
                        });
                    }
                } catch(e) {}

                try {
                    if (window.anime && anime.running) {
                        anime.running.slice().forEach(a => {
                            try { a.seek(a.duration); } catch(e) {}
                        });
                    }
                } catch(e) {}

                document.querySelectorAll('.wow').forEach(el => {
                    el.classList.add('animated');
                    el.style.setProperty('visibility', 'visible', 'important');
                    el.style.setProperty('opacity', '1', 'important');
                    el.style.setProperty('animation-name', 'none', 'important');
                });
                document.querySelectorAll('[class*="animate__"]').forEach(el => {
                    el.style.setProperty('visibility', 'visible', 'important');
                    el.style.setProperty('opacity', '1', 'important');
                    el.style.setProperty('animation-name', 'none', 'important');
                });

                document.querySelectorAll('[data-aos]').forEach(el => {
                    el.classList.add('aos-animate');
                });

                document.querySelectorAll('.elementor-invisible').forEach(el => {
                    el.classList.remove('elementor-invisible');
                    el.style.setProperty('opacity', '1', 'important');
                    el.style.setProperty('visibility', 'visible', 'important');
                });

                document.querySelectorAll('video').forEach(v => {
                    try {
                        v.pause();
                        if (v.duration && v.currentTime < 0.1) v.currentTime = 0.1;
                    } catch(e) {}
                });
            }
        """)
        page.wait_for_timeout(300)
    except Exception as e:
        logging.warning(f"_finish_all_animations: {e}")


# ─── #G: slider walkthrough ────────────────────────────────────────────────────

def _walk_through_sliders(page):
    try:
        page.evaluate("""
            () => {
                // ─── Swiper API: iterate all slides via instance ─────────
                document.querySelectorAll('.swiper-container, .swiper, [class*="swiper"]').forEach(el => {
                    const sw = el.swiper;
                    if (sw && sw.slides && sw.slides.length > 0) {
                        for (let i = 0; i < sw.slides.length; i++) {
                            try { sw.slideTo(i, 0); } catch(e) {}
                        }
                        try { sw.slideTo(0, 0); } catch(e) {}
                        if (sw.lazy && sw.lazy.load) {
                            try { sw.lazy.load(); } catch(e) {}
                        }
                        if (sw.update) {
                            try { sw.update(); } catch(e) {}
                        }
                    }
                });

                // ─── Elementor Swiper instances (stored on widget wrappers) ──
                if (window.elementorFrontend) {
                    document.querySelectorAll('.elementor-widget-container').forEach(w => {
                        const swEl = w.querySelector('.swiper-container, .swiper');
                        if (swEl && swEl.swiper) {
                            const sw = swEl.swiper;
                            for (let i = 0; i < sw.slides.length; i++) {
                                try { sw.slideTo(i, 0); } catch(e) {}
                            }
                            try { sw.slideTo(0, 0); } catch(e) {}
                            if (sw.lazy && sw.lazy.load) try { sw.lazy.load(); } catch(e) {}
                            if (sw.update) try { sw.update(); } catch(e) {}
                        }
                    });
                }

                // ─── Dot clicking for Slick/Flickity/Owl ─────────────────
                const dotSelectors = [
                    '.slick-dots li',
                    '.flickity-page-dots .dot',
                    '.owl-dots .owl-dot',
                    '.swiper-pagination-bullet',
                ];
                dotSelectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(dot => {
                        try { dot.click(); } catch(e) {}
                    });
                });

                document.querySelectorAll('.gv_panelNavNext').forEach(btn => {
                    for (let i = 0; i < 10; i++) {
                        try { btn.click(); } catch(e) {}
                    }
                });

                const nextSelectors = [
                    '.slick-next', '.owl-next', '.flickity-prev-next-button.next',
                    '.swiper-button-next',
                ];
                nextSelectors.forEach(sel => {
                    const btn = document.querySelector(sel);
                    if (btn) {
                        for (let i = 0; i < 10; i++) {
                            try { btn.click(); } catch(e) {}
                        }
                    }
                });
            }
        """)
        page.wait_for_timeout(1500)
    except Exception as e:
        logging.warning(f"_walk_through_sliders: {e}")


# ─── #F: lepszy wait_for_images ──────────────────────────────────────────────

def _wait_for_images(page, timeout=5000):
    try:
        page.wait_for_function("""
            () => {
                const imgs = Array.from(document.querySelectorAll('img'));
                if (imgs.length === 0) return true;
                return imgs.every(img =>
                    img.complete && (img.naturalWidth > 0 || !img.src || img.src.startsWith('data:'))
                );
            }
        """, timeout=timeout)
    except Exception:
        pass

def _wait_for_fonts(page):
    try:
        page.evaluate("async () => { await document.fonts.ready; }")
        page.wait_for_timeout(300)
    except Exception:
        pass

# ─── scroll + navigation ──────────────────────────────────────────────────────

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
                }, 80);
                setTimeout(() => { clearInterval(timer); window.scrollTo(0, 0); resolve(); }, 8000);
            })
        """, timeout=10000)
        page.wait_for_timeout(1000)
    except Exception:
        pass


# ─── SR7 / RevSlider ─────────────────────────────────────────────────────────

def _force_sr7_render(page):
    try:
        has_sr7 = page.evaluate("() => document.querySelector('sr7-module') !== null")
    except Exception:
        return
    if not has_sr7:
        return

    for _ in range(15):
        try:
            ready = page.evaluate("""
                () => {
                    if (window.SR7 && window.SR7.M) {
                        for (const k of Object.keys(window.SR7.M)) {
                            if (window.SR7.M[k] && window.SR7.M[k].state === true) return true;
                        }
                    }
                    return false;
                }
            """)
            if ready:
                return
        except Exception:
            pass
        page.wait_for_timeout(500)

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
                        bg.style.setProperty('display', 'block', 'important');
                        bg.style.setProperty('position', 'absolute', 'important');
                        bg.style.setProperty('inset', '0', 'important');
                    }
                });
            }
        """)
    except Exception:
        pass


def _force_revslider_render(page):
    try:
        has_rs = page.evaluate("() => document.querySelector('rs-module') !== null")
    except Exception:
        return
    if not has_rs:
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
                document.querySelectorAll('.rs-loader, rs-loader, .tp-loader').forEach(el => {
                    el.style.setProperty('display', 'none', 'important');
                });
            }
        """)
    except Exception:
        pass


# ─── #H: route blocking analytics ─────────────────────────────────────────────

ANALYTICS_PATTERNS = [
    'google-analytics.com', 'googletagmanager.com', 'g.doubleclick.net',
    'facebook.com/tr', 'connect.facebook.net',
    'hotjar.com', 'static.hotjar.com',
    'clarity.ms', 'mixpanel.com', 'segment.com', 'segment.io',
    'amplitude.com', 'sentry.io', 'rollbar.com', 'bugsnag.com',
    'doubleclick.net', 'adservice.google',
    'tiktok.com/i18n/pixel', 'analytics.tiktok.com',
    'linkedin.com/li.lms-analytics',
    'snapchat.com/p', 'pinterest.com/ct',
    'criteo.com', 'taboola.com', 'outbrain.com',
]

def _make_block_handler():
    def _block(route, request):
        if not _CFG.get('block_analytics', True):
            return route.continue_()
        url = request.url
        if any(p in url for p in ANALYTICS_PATTERNS):
            return route.abort()
        return route.continue_()
    return _block

# ─── konsens cookies ──────────────────────────────────────────────────────────

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
            'webwave-cookie-consent',
        ]
        context.add_cookies([
            {'name': n, 'value': 'true', 'domain': domain, 'path': '/'}
            for n in names
        ])
    except Exception:
        pass

# ─── navigation + screenshot ──────────────────────────────────────────────────

def _navigate(page, url: str, retries: int = 2) -> Tuple[bool, str]:
    for attempt in range(1 + retries):
        try:
            page.goto(url, wait_until='load', timeout=45000)
            try:
                page.wait_for_load_state('networkidle', timeout=8000)
            except Exception:
                pass
            return True, page.url
        except Exception:
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                return True, page.url
            except Exception as e:
                print(f"   [NAV ERR] {e}")
                return False, url


def _take_screenshot(page, output_path: Path):
    max_h = _CFG.get('max_screenshot_height', 15000)
    try:
        page_height = page.evaluate("() => document.body.scrollHeight")
    except Exception:
        page_height = 0

    if page_height > max_h:
        print(f"   [!] strona ma {page_height}px — przycinam do {max_h}px")
        try:
            page.screenshot(
                path=str(output_path),
                clip={'x': 0, 'y': 0, 'width': _CFG.get('viewport_width', 1440), 'height': max_h}
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


# ─── #I: diagnostyka ──────────────────────────────────────────────────────────

def _run_diagnostics(page, page_url: str):
    try:
        diag = page.evaluate("""
            () => {
                const bad = {
                    invisible_with_content: 0,
                    broken_images: 0,
                    placeholder_images: 0,
                    untriggered_animations: 0,
                    empty_bg_elements: 0,
                };
                document.querySelectorAll('*').forEach(el => {
                    const s = getComputedStyle(el);
                    const txt = (el.textContent || '').trim();
                    if (parseFloat(s.opacity) < 0.1 && s.display !== 'none' && txt.length > 5
                        && !el.querySelector('*')) bad.invisible_with_content++;
                });
                document.querySelectorAll('img').forEach(img => {
                    if (img.complete && img.src && img.naturalWidth === 0
                        && !img.src.startsWith('data:')) bad.broken_images++;
                    if (img.src && img.src.startsWith('data:image/gif;base64')
                        && img.src.length < 200) bad.placeholder_images++;
                });
                try {
                    if (document.getAnimations) {
                        bad.untriggered_animations = document.getAnimations()
                            .filter(a => a.playState === 'running').length;
                    }
                } catch(e) {}
                document.querySelectorAll('[data-background-image], [data-lazy-background-image], [data-bg]').forEach(el => {
                    if (!el.style.backgroundImage || el.style.backgroundImage === 'none') {
                        bad.empty_bg_elements++;
                    }
                });
                return bad;
            }
        """)
        if any(v > 0 for v in diag.values()):
            msg = f"  [diag] {page_url}: " + ", ".join(f"{k}={v}" for k, v in diag.items() if v > 0)
            print(msg)
            logging.warning(msg)
    except Exception:
        pass


# ─── asset capture & html rewriting ──────────────────────────────────────────

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
        r'(?P<attr>(?:src|href|poster|data-src|data-lazy-src|data-lazy-load-src|'
        r'data-bg|data-bg-url|data-bg-image|data-background-image|'
        r'data-lazy-background-image|data-retina|data-image)'
        r'\s*=\s*["\'])(?P<url>[^"\']+)(?P<end>["\'])',
        re.IGNORECASE
    )
    srcset_pat = re.compile(
        r'(?P<attr>(?:srcset|data-srcset|data-lazy-srcset)\s*=\s*["\'])'
        r'(?P<val>[^"\']+)(?P<end>["\'])',
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
            }
        """)
    except Exception:
        pass


def _fetch_missing_css_assets(css_assets, captured, assets_dir, fname_counts, session):
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


# ─── główna sekwencja przygotowania strony ────────────────────────────────────

def _prepare_page(page, aggressive: bool):
    close_popups_aggressive(page) if aggressive else close_popups(page)
    _scroll_and_wait(page)
    _force_lazy_load(page)
    _force_sr7_render(page)
    _force_revslider_render(page)
    _walk_through_sliders(page)
    _force_lazy_load(page)
    close_popups(page)
    _finish_all_animations(page)
    _wait_for_images(page, timeout=8000)
    _wait_for_fonts(page)
    try:
        page.wait_for_load_state('networkidle', timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    _finish_all_animations(page)
    _convert_blobs_to_base64(page)


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

    if actual_url != page_url:
        print(f"   → redirect: {actual_url}")
    else:
        print(f"   → {actual_url}")

    _prepare_page(page, aggressive)

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

    try:
        extra_images = page.evaluate(r"""
            () => {
                const urls = new Set();
                const addUrl = (u) => {
                    if (!u) return;
                    if (u.startsWith('//')) u = 'https:' + u;
                    if (u.startsWith('http')) urls.add(u);
                };
                document.querySelectorAll('img[src^="http"]').forEach(img => {
                    addUrl(img.getAttribute('src'));
                });
                document.querySelectorAll('[srcset]').forEach(el => {
                    (el.getAttribute('srcset') || '').split(',').forEach(part => {
                        addUrl(part.trim().split(' ')[0]);
                    });
                });
                ['data-srcset','data-lazy-srcset'].forEach(a => {
                    document.querySelectorAll('['+a+']').forEach(el => {
                        (el.getAttribute(a) || '').split(',').forEach(part => {
                            addUrl(part.trim().split(' ')[0]);
                        });
                    });
                });
                ['data-bg','data-lazy-bg','data-bg-url','data-background-image','data-lazy-background-image','data-lazy-load-src'].forEach(a => {
                    document.querySelectorAll('['+a+']').forEach(el => addUrl(el.getAttribute(a)));
                });
                document.querySelectorAll('[style*="background-image"]').forEach(el => {
                    const m = (el.getAttribute('style') || '').match(/url\(['"]?([^'")]+)['"]?\)/g);
                    if (m) m.forEach(match => {
                        const u = match.replace(/url\(['"]?/, '').replace(/['"]?\)/, '');
                        addUrl(u);
                    });
                });
                document.querySelectorAll('[data-ww_rwd]').forEach(el => {
                    try {
                        const raw = el.getAttribute('data-ww_rwd').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
                        const data = JSON.parse(raw);
                        const collect = (obj) => {
                            if (typeof obj === 'string' && /\.(png|jpg|jpeg|gif|webp|svg|avif)/i.test(obj)) {
                                addUrl(obj.startsWith('/') ? location.origin + obj : obj);
                            } else if (obj && typeof obj === 'object') {
                                Object.values(obj).forEach(collect);
                            }
                        };
                        collect(data);
                    } catch(e) {}
                });
                document.querySelectorAll('figure script[type="application/json"]').forEach(s => {
                    try {
                        const data = JSON.parse(s.textContent);
                        if (data.rwdProperties) {
                            Object.values(data.rwdProperties).forEach(m => {
                                if (m && m.imageSrc) {
                                    addUrl(m.imageSrc.startsWith('/') ? location.origin + m.imageSrc : m.imageSrc);
                                }
                            });
                        }
                    } catch(e) {}
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
        logging.warning(f"extra_images: {e}")

    html_ok = False
    try:
        html = page.content()
        html = _rewrite_html(html, captured, page_url)
        (output_dir / 'index.html').write_text(html, encoding='utf-8', errors='replace')
        _fetch_missing_css_assets(css_assets, captured, assets_dir, fname_counts, session)
        _rewrite_css_assets(css_assets, captured)

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

    _run_diagnostics(page, page_url)

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

    if actual_url != page_url:
        print(f"   → redirect: {actual_url}")
    else:
        print(f"   → {actual_url}")

    _prepare_page(page, aggressive)

    shot_ok = _take_screenshot(page, output_path)
    if shot_ok:
        try:
            kb = output_path.stat().st_size // 1024
            print(f"   saved  {output_path.name}  ({kb} KB)")
        except Exception:
            pass

    _run_diagnostics(page, page_url)

    page.close()
    return shot_ok


# ─── zip helpers ──────────────────────────────────────────────────────────────

SKIP_DIRS = {'__pycache__', '.git', '.svn', '.hg', 'node_modules', '.DS_Store',
             '.tox', '.venv', 'venv', '.mypy_cache'}

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


# ─── #B (v4.1): per-thread playwright + browser ───────────────────────────────
#
# Playwright sync API jest greenlet-bound — jeden browser NIE może być
# współdzielony między wątkami (ThreadPoolExecutor). Rozwiązanie:
# thread-local storage, każdy wątek startuje własny playwright+browser.

_thread_local = threading.local()


def _get_thread_browser():
    """Zwraca browser dla bieżącego wątku. Tworzy jeśli nie istnieje."""
    if not getattr(_thread_local, 'browser', None):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[!] Playwright not installed. pip install playwright && playwright install chromium")
            sys.exit(1)
        _thread_local.pw = sync_playwright().start()
        _thread_local.browser = _thread_local.pw.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
            ],
        )
    return _thread_local.browser


def _close_thread_browser():
    """Zamyka browser i playwright dla bieżącego wątku."""
    try:
        if getattr(_thread_local, 'browser', None):
            _thread_local.browser.close()
            _thread_local.browser = None
    except Exception:
        pass
    try:
        if getattr(_thread_local, 'pw', None):
            _thread_local.pw.stop()
            _thread_local.pw = None
    except Exception:
        pass


def _make_context(browser=None):
    """Tworzy nowy context. Jeśli browser=None, używa thread-local browsera."""
    b = browser or _get_thread_browser()
    ctx = b.new_context(
        viewport={
            'width':  _CFG.get('viewport_width',  1440),
            'height': _CFG.get('viewport_height', 900),
        },
        bypass_csp=True,
        user_agent=NORMAL_USER_AGENT,
        reduced_motion='reduce',
        device_scale_factor=1,
        color_scheme='light',
        locale='pl-PL',
    )
    ctx.add_init_script(_INIT_SCRIPT)
    if _CFG.get('block_analytics', True):
        ctx.route('**/*', _make_block_handler())
    return ctx


def run(urls: list, base_output: Path, mode: str, keep_folders: bool = False):
    normalized = [
        u if u.startswith(('http://', 'https://')) else 'https://' + u
        for u in urls
    ]

    # Sprawdź czy playwright jest dostępny (szybki fail)
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("[!] Playwright not installed. pip install playwright && playwright install chromium")
        sys.exit(1)

    _run_inner(normalized, base_output, mode, keep_folders)

    print("\n" + "─" * 50)
    print("  RESULTS")
    print("─" * 50)
    for z in sorted(base_output.glob('*.zip')):
        mb = z.stat().st_size / (1024 * 1024)
        print(f"  {z.name}  ({mb:.1f} MB)")
    print()


def _run_inner(normalized, base_output, mode, keep_folders):
    aggressive = mode.startswith('clean-')
    effective = mode.replace('clean-', '', 1)
    mode_label = f"CLEAN + {effective.upper()}" if aggressive else effective.upper()
    total_pages = len(normalized)
    workers = _CFG.get('workers', 1)
    logging.info(f"mode={mode_label} pages={total_pages} workers={workers} output={base_output}")

    _print_lock = threading.Lock()
    _counter_lock = threading.Lock()
    _page_counter = [0]

    def _safe_print(*args, **kwargs):
        with _print_lock:
            print(*args, **kwargs)

    def _next_progress():
        with _counter_lock:
            _page_counter[0] += 1
            return f"[{_page_counter[0]}/{total_pages}]"

    # ── screenshots ──────────────────────────────────────────────────────────
    if effective == 'screenshots':
        _safe_print(f"\n  mode    : {mode_label}")
        _safe_print(f"  pages   : {total_pages}")
        _safe_print(f"  workers : {workers}\n")

        by_domain = defaultdict(list)
        for url in normalized:
            by_domain[get_domain(url)].append(url)

        tmp_dir = base_output / '_screenshots_tmp'
        tmp_dir.mkdir(parents=True, exist_ok=True)

        ok_count_ref = [0]
        fail_count_ref = [0]
        domain_shots_map = defaultdict(list)
        shots_lock = threading.Lock()

        def _worker_screenshot(url):
            domain = get_domain(url)
            progress = _next_progress()
            fname = get_screenshot_filename(url)
            out_path = tmp_dir / fname
            _safe_print(f"\n  {progress} {url}")
            logging.info(f"{progress} screenshot {url}")
            # Każdy wątek tworzy własny context ze swojego thread-local browsera
            ctx = _make_context()
            try:
                success = process_screenshot_only(url, ctx, out_path, aggressive=aggressive, progress=progress)
            finally:
                try: ctx.close()
                except Exception: pass
                _close_thread_browser()
            with shots_lock:
                if success:
                    domain_shots_map[domain].append(out_path)
                    ok_count_ref[0] += 1
                else:
                    fail_count_ref[0] += 1
                    _safe_print(f"   [FAIL] {url}")
                    logging.error(f"[FAIL] screenshot {url}")
            return url, success

        all_urls = [u for domain_urls in by_domain.values() for u in domain_urls]
        for domain in by_domain:
            _safe_print(f"\n  [*] {domain}  ({len(by_domain[domain])} pages)")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker_screenshot, url): url for url in all_urls}
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as exc:
                    _safe_print(f"   [ERR] {futures[f]}: {exc}")
                    logging.error(f"[ERR] {futures[f]}: {exc}")

        for domain, shots in domain_shots_map.items():
            if shots:
                zip_path = base_output / get_zip_name(domain, mode='screenshots')
                pack_files_to_zip(shots, zip_path)

        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        _safe_print(f"\n  done  : {ok_count_ref[0]} ok  /  {fail_count_ref[0]} failed")
        logging.info(f"done: {ok_count_ref[0]} ok, {fail_count_ref[0]} failed")
        return

    # ── full / crawl ─────────────────────────────────────────────────────────
    is_crawl = effective == 'crawl'

    by_domain = defaultdict(list)
    for url in normalized:
        by_domain[get_domain(url)].append(url)

    _safe_print(f"\n  mode    : {mode_label}")
    _safe_print(f"  domains : {len(by_domain)}")
    _safe_print(f"  pages   : {total_pages}")
    _safe_print(f"  workers : {workers}\n")

    for domain, domain_urls in by_domain.items():
        zip_path = base_output / get_zip_name(domain, mode='crawl' if is_crawl else 'full')
        domain_tmp = base_output / sanitize_name(domain)
        domain_tmp.mkdir(parents=True, exist_ok=True)

        _safe_print(f"\n  [*] {domain}  ({len(domain_urls)} pages)")
        logging.info(f"domain={domain} pages={len(domain_urls)}")

        def _worker_full(url, domain_tmp=domain_tmp):
            progress = _next_progress()
            sub = get_subfolder_name(url)
            page_dir = domain_tmp / sub
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / 'meta.txt').write_text(
                f"URL: {url}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
                encoding='utf-8'
            )
            _safe_print(f"\n  {progress} {url}")
            _safe_print(f"      -> {sub}/")
            logging.info(f"{progress} {url} -> {sub}/")
            # Każdy wątek tworzy własny context ze swojego thread-local browsera
            ctx = _make_context()
            try:
                html_ok, shot_ok = process_full(url, ctx, page_dir, aggressive=aggressive, progress=progress)
            finally:
                try: ctx.close()
                except Exception: pass
                _close_thread_browser()
            status = '[OK]' if (html_ok or shot_ok) else '[FAIL]'
            _safe_print(f"   {status}")
            logging.info(f"{status} html={html_ok} shot={shot_ok}")
            return html_ok, shot_ok

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker_full, url): url for url in domain_urls}
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as exc:
                    _safe_print(f"   [ERR] {futures[f]}: {exc}")
                    logging.error(f"[ERR] {futures[f]}: {exc}")

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
        parser.add_argument('--max-pages', type=int, default=None)
        parser.add_argument('--config', default=None)
        args = parser.parse_args()

        load_config(args.config)
        if args.max_pages is not None:
            _CFG['max_pages'] = args.max_pages
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
                cr_urls = crawl_internal_links(seed_url, session, max_pages=_CFG.get('max_pages', 50))
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

    load_config()
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
            cr_urls = crawl_internal_links(seed_url, session, max_pages=_CFG.get('max_pages', 50))
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