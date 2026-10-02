"""Retrieval layer: finds product pages on Pakistani stores and extracts facts.

Strategy (free, no store API keys required):
  1. Site-restricted web search per store (Serper if SERPER_API_KEY is set, else DuckDuckGo via `ddgs`).
  2. Fetch each candidate product page and read schema.org JSON-LD / Open Graph metadata
     (price, currency, availability, rating, image, brand).
  3. Fall back to a price found in the search snippet when the page cannot be read.

IMPORTANT: only fetch what each store's Terms of Service and robots.txt allow. For production,
replace/augment this module with official affiliate feeds or partner APIs (see README).
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .config import PLATFORMS_BY_KEY
from .models import Listing

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
]
_PRICE_RE = re.compile(r"(?:Rs\.?|PKR|\u20a8)\s*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)", re.I)
_SKIP_PATH = re.compile(r"/(search|catalog|category|categories|tag|tags|blog|blogs|brands?|cart|account|checkout)(/|$)", re.I)


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-PK,en;q=0.9",
    }


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
        if not m:
            return None
        v = float(m.group())
    return v if 0 < v < 1e8 else None


def _norm_url(url: str) -> str:
    try:
        u = urlparse(url.strip())
    except Exception:
        return ""
    if u.scheme not in ("http", "https") or not u.netloc:
        return ""
    q = [(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith(("utm_", "gclid", "fbclid", "spm"))]
    return urlunparse((u.scheme, u.netloc, u.path, "", urlencode(q), ""))


# ----------------------------------------------------------------------------- web search
def _web_search(query: str, domain: str, n: int, notes: List[str]) -> List[Dict[str, str]]:
    """Try several backends. Every failure is recorded in `notes` so the UI can explain empty results."""
    q = f"{query} site:{domain}"
    serper_key = os.environ.get("SERPER_API_KEY", "").strip()
    if serper_key:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": q, "gl": "pk", "num": n + 4},
                timeout=12,
            )
            r.raise_for_status()
            rows = r.json().get("organic", [])
            if rows:
                notes.append(f"serper ok ({len(rows)})")
                return [{"title": o.get("title", ""), "url": o.get("link", ""), "snippet": o.get("snippet", "")} for o in rows]
            notes.append("serper returned 0")
        except Exception as e:  # noqa: BLE001
            notes.append(f"serper error: {str(e)[:70]}")
    try:
        from ddgs import DDGS
    except ImportError:
        notes.append("ddgs not installed")
        return []
    attempts = [(q, "auto"), (q, "bing"), (q, "brave"), (f"{query} {domain.split('.')[0]} Pakistan price", "auto")]
    for i, (qq, backend) in enumerate(attempts):
        try:
            rows = DDGS().text(qq, region="pk-en", max_results=n + 6, backend=backend) or []
            hits = [r for r in rows if domain in (r.get("href", "") or "")]
            if hits:
                notes.append(f"ddgs/{backend} ok ({len(hits)})")
                return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in hits]
            notes.append(f"ddgs/{backend}: {len(rows)} rows, 0 on {domain}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"ddgs/{backend} error: {str(e)[:70]}")
        time.sleep(0.8 + 0.4 * i)
    return []


def _daraz_direct(query: str, n: int, notes: List[str]) -> List[Listing]:
    """Daraz exposes its own search results as JSON; works when the server IP is not blocked."""
    try:
        r = requests.get("https://www.daraz.pk/catalog/", params={"ajax": "true", "q": query},
                         headers={**_headers(), "Accept": "application/json, text/plain, */*"}, timeout=10)
        if r.status_code != 200:
            notes.append(f"daraz direct HTTP {r.status_code}")
            return []
        items = (r.json().get("mods") or {}).get("listItems") or []
    except Exception as e:  # noqa: BLE001
        notes.append(f"daraz direct error: {str(e)[:70]}")
        return []
    out: List[Listing] = []
    for it in items[: n + 2]:
        url = str(it.get("itemUrl") or it.get("productUrl") or "")
        url = ("https:" + url) if url.startswith("//") else url
        url = _norm_url(url)
        if not url:
            continue
        in_stock = it.get("inStock")
        out.append(Listing(
            id="", platform_key="daraz", platform="Daraz", title=str(it.get("name", ""))[:160] or url, url=url,
            price=_to_float(it.get("price")), original_price=_to_float(it.get("originalPrice")), price_source="page",
            availability="In stock" if in_stock is True else ("Out of stock" if in_stock is False else ""),
            rating=_to_float(it.get("ratingScore")), review_count=int(_to_float(it.get("review")) or 0) or None,
            image=("https:" + it["image"]) if str(it.get("image", "")).startswith("//") else str(it.get("image", "")),
            seller=str(it.get("sellerName", ""))[:80], page_checked=True,
        ))
        if len(out) >= n:
            break
    notes.append(f"daraz direct ok ({len(out)})" if out else "daraz direct: 0 items")
    return out


# ----------------------------------------------------------------------------- page parsing
def _iter_products(node: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(node, list):
        for x in node:
            yield from _iter_products(x)
    elif isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Product" in types or "ProductGroup" in types:
            yield node
        for k in ("@graph", "mainEntity", "itemListElement", "item"):
            if k in node:
                yield from _iter_products(node[k])


def _offer_info(offers: Any) -> Tuple[Optional[float], str, str, str]:
    if isinstance(offers, list):
        for o in offers:
            res = _offer_info(o)
            if res[0]:
                return res
        return None, "", "", ""
    if not isinstance(offers, dict):
        return None, "", "", ""
    price = _to_float(offers.get("price") or offers.get("lowPrice"))
    spec = offers.get("priceSpecification")
    if price is None and isinstance(spec, dict):
        price = _to_float(spec.get("price"))
    cur = str(offers.get("priceCurrency") or "")
    avail = str(offers.get("availability") or "").rsplit("/", 1)[-1]
    seller = offers.get("seller")
    seller_name = seller.get("name", "") if isinstance(seller, dict) else (seller if isinstance(seller, str) else "")
    return price, cur, avail, seller_name


def _nice_availability(raw: str) -> str:
    r = raw.lower()
    if "instock" in r or "in stock" in r:
        return "In stock"
    if "outofstock" in r or "soldout" in r or "out of stock" in r:
        return "Out of stock"
    if "preorder" in r:
        return "Pre-order"
    if "limited" in r:
        return "Limited stock"
    return ""


def _parse_page(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, Any] = {}

    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for prod in _iter_products(data):
            price, cur, avail, seller = _offer_info(prod.get("offers"))
            if cur and cur.upper() not in ("PKR", "RS", "RS."):
                price = None  # foreign-currency price: do not mix with PKR
            out.setdefault("title", str(prod.get("name") or "")[:200])
            if price and not out.get("price"):
                out["price"] = price
            if avail and not out.get("availability"):
                out["availability"] = _nice_availability(avail)
            if seller and not out.get("seller"):
                out["seller"] = str(seller)[:80]
            brand = prod.get("brand")
            if brand and not out.get("brand"):
                out["brand"] = (brand.get("name") if isinstance(brand, dict) else str(brand))[:60]
            img = prod.get("image")
            if img and not out.get("image"):
                img = img[0] if isinstance(img, list) and img else img
                out["image"] = img.get("url", "") if isinstance(img, dict) else str(img)
            agg = prod.get("aggregateRating")
            if isinstance(agg, dict) and not out.get("rating"):
                out["rating"] = _to_float(agg.get("ratingValue"))
                rc = _to_float(agg.get("reviewCount") or agg.get("ratingCount"))
                out["reviews"] = int(rc) if rc else None
            if prod.get("description") and not out.get("description"):
                out["description"] = re.sub(r"\s+", " ", str(prod["description"]))[:500]
        if out.get("price"):
            break

    def meta(*names: str) -> str:
        for n in names:
            el = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"itemprop": n})
            if el and el.get("content"):
                return str(el["content"]).strip()
        return ""

    if not out.get("price"):
        cur = meta("product:price:currency", "og:price:currency", "priceCurrency")
        price = _to_float(meta("product:price:amount", "og:price:amount", "price"))
        if price and (not cur or cur.upper() in ("PKR", "RS")):
            out["price"] = price
    if not out.get("original_price"):
        out["original_price"] = _to_float(meta("product:original_price:amount", "og:price:standard_amount"))
    if not out.get("title"):
        out["title"] = meta("og:title")[:200]
    if not out.get("image"):
        out["image"] = meta("og:image")
    if not out.get("description"):
        out["description"] = meta("og:description", "description")[:500]
    return out


def _enrich(listing: Listing) -> None:
    try:
        r = requests.get(listing.url, headers=_headers(), timeout=7, allow_redirects=True)
    except requests.RequestException:
        return
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        return
    info = _parse_page(r.text[:1_500_000])
    listing.page_checked = True
    if info.get("title"):
        listing.title = info["title"]
    if info.get("price"):
        listing.price, listing.price_source = info["price"], "page"
    if info.get("original_price") and listing.price and info["original_price"] > listing.price:
        listing.original_price = info["original_price"]
    listing.availability = info.get("availability", "") or listing.availability
    listing.brand = info.get("brand", "") or listing.brand
    listing.rating = info.get("rating") or listing.rating
    listing.review_count = info.get("reviews") or listing.review_count
    listing.seller = info.get("seller", "") or listing.seller
    listing.description = info.get("description", "") or listing.description
    if str(info.get("image", "")).startswith("http"):
        listing.image = info["image"]


# ----------------------------------------------------------------------------- public API
def search_platform(platform_key: str, query: str, per_platform: int = 3, diag: Optional[List[str]] = None) -> List[Listing]:
    p = PLATFORMS_BY_KEY[platform_key]
    notes: List[str] = []
    try:
        if p.key == "daraz":
            direct = _daraz_direct(query, per_platform, notes)
            if direct:
                return direct
        seen, listings = set(), []
        for row in _web_search(query, p.domain, per_platform, notes):
            url = _norm_url(row.get("url", ""))
            if not url or url in seen:
                continue
            host = urlparse(url).netloc.lower()
            if not (host == p.domain or host.endswith("." + p.domain)):
                continue
            if _SKIP_PATH.search(urlparse(url).path + "/"):
                continue
            seen.add(url)
            text = f"{row.get('title', '')} {row.get('snippet', '')}"
            m = _PRICE_RE.search(text)
            snippet_price = _to_float(m.group(1)) if m else None
            listings.append(Listing(
                id="", platform_key=p.key, platform=p.name,
                title=re.sub(r"\s+", " ", row.get("title", ""))[:160] or url,
                url=url, price=snippet_price, price_source="snippet" if snippet_price else "",
                snippet=re.sub(r"\s+", " ", row.get("snippet", ""))[:300],
            ))
            if len(listings) >= per_platform:
                break
        for item in listings:
            _enrich(item)
        checked = sum(1 for l in listings if l.page_checked)
        priced = sum(1 for l in listings if l.price)
        notes.append(f"{len(listings)} listings, {checked} pages read, {priced} priced")
        return listings
    finally:
        if diag is not None:
            diag.append(f"{p.name}: " + " | ".join(notes))


def gather(query: str, platform_keys: List[str], per_platform: int = 3, timeout: int = 55,
           diag: Optional[List[str]] = None) -> List[Listing]:
    """Query all stores in parallel; never raises - failing stores simply return nothing."""
    if not platform_keys:
        return []
    order = {k: i for i, k in enumerate(platform_keys)}
    out: List[Listing] = []
    ex = ThreadPoolExecutor(max_workers=min(6, len(platform_keys)))
    futures = {ex.submit(search_platform, k, query, per_platform, diag): k for k in platform_keys}
    try:
        for fut in as_completed(futures, timeout=timeout):
            try:
                out.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                if diag is not None:
                    diag.append(f"{futures[fut]}: crashed {str(e)[:80]}")
    except Exception:
        if diag is not None:
            diag.append("overall search timeout - partial results kept")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    out.sort(key=lambda l: order.get(l.platform_key, 99))
    return out


def self_test() -> List[str]:
    """Quick connectivity check shown in the sidebar: which retrieval paths work from this server?"""
    lines: List[str] = []
    notes: List[str] = []
    rows = _web_search("samsung galaxy", "daraz.pk", 3, notes)
    lines += [f"search: {n}" for n in notes] or ["search: no notes"]
    lines.append(f"search results usable: {len(rows)}")
    n2: List[str] = []
    d = _daraz_direct("samsung galaxy", 3, n2)
    lines += [f"daraz: {n}" for n in n2]
    for dom in ("telemart.pk", "shophive.com"):
        try:
            r = requests.get(f"https://{dom}/", headers=_headers(), timeout=8)
            lines.append(f"{dom}: HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"{dom}: {str(e)[:80]}")
    return lines
