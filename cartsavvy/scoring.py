"""Deterministic ranking. All numbers shown to the user come from here, never from the LLM."""
from __future__ import annotations

import re
import statistics
from typing import Any, Dict, Iterable, List, Optional

from .config import PLATFORMS_BY_KEY, WEIGHT_PRESETS, delivery_estimate
from .models import Listing, ListingJudgement, Preferences


def _warranty(text: str):
    t = text.lower()
    if re.search(r"no warranty|without warranty|non[- ]warranty", t):
        return 20, "No warranty"
    if re.search(r"official warranty|brand warranty|manufacturer warranty|company warranty", t):
        return 100, "Official warranty"
    m = re.search(r"(\d+)[\s-]*(year|yr|month)s?\s*(?:official\s*)?warranty", t)
    if m:
        unit = "year" if m.group(1) == "1" and m.group(2).startswith("y") else m.group(2)
        return 85, f"{m.group(1)}-{unit} warranty"
    if "warranty" in t or "guarantee" in t:
        return 75, "Warranty mentioned"
    return 50, "Not stated"


def _delivery_score(lo: int, hi: int, deadline: int) -> float:
    score = max(15.0, 100.0 - 9.0 * hi)
    if deadline and lo > deadline:
        score *= 0.4
    return score


def score_results(listings: Iterable[Listing], judgements: Dict[str, ListingJudgement],
                  prefs: Preferences, platforms_searched: List[str]) -> Dict[str, Any]:
    weights = WEIGHT_PRESETS.get(prefs.priority, WEIGHT_PRESETS["balanced"])
    rows: List[Dict[str, Any]] = []
    excluded_budget = 0
    platforms_with_results = set()

    for l in listings:
        platforms_with_results.add(l.platform_key)
        j = judgements.get(l.id)
        match = j.match_type if j else "similar"
        conf = max(0.0, min(1.0, j.confidence)) if j else 0.4
        if match == "irrelevant":
            continue
        if prefs.budget_max and l.price and l.price > prefs.budget_max:
            excluded_budget += 1
            continue
        p = PLATFORMS_BY_KEY[l.platform_key]
        lo, hi, dlabel = delivery_estimate(p, prefs.city)
        w_score, w_label = _warranty(f"{l.title} {l.description} {l.snippet}")
        trust = p.trust * 100
        if l.rating:
            trust = 0.5 * trust + 0.5 * (l.rating / 5.0 * 100)
        payment = min(100, 25 * len(p.payments))
        if prefs.prefer_cod and "COD" not in p.payments:
            payment = 0
        attrs = [(a.name, a.value) for a in (j.attributes if j else [])][:6]
        disc = None
        if l.original_price and l.price and l.original_price > l.price:
            disc = round((1 - l.price / l.original_price) * 100)
        rows.append({
            "id": l.id, "platform": l.platform, "platform_key": l.platform_key,
            "title": l.title, "url": l.url, "image": l.image,
            "price": l.price, "original_price": l.original_price, "discount_pct": disc,
            "price_source": l.price_source, "availability": l.availability or "Check on store",
            "rating": l.rating, "review_count": l.review_count, "seller": l.seller,
            "delivery_label": dlabel, "delivery_min": lo, "delivery_max": hi,
            "warranty": w_label, "payments": list(p.payments),
            "match_type": match, "confidence": conf, "attributes": attrs,
            "reason": j.reason if j else "Not evaluated by the research agent",
            "_s": {
                "delivery": _delivery_score(lo, hi, prefs.deadline_days), "trust": trust,
                "warranty": w_score, "payment": payment,
                "match": conf * 100 * (1.0 if match == "exact" else 0.65),
            },
            "flags": [],
        })

    # Outlier guard: a price far below the median of exact matches is suspicious (fake/foreign/accessory listing).
    exact_prices = [r["price"] for r in rows if r["price"] and r["match_type"] == "exact"]
    med = statistics.median(exact_prices) if len(exact_prices) >= 3 else None
    for r in rows:
        r["suspect"] = bool(med and r["price"] and r["match_type"] == "exact" and r["price"] < 0.6 * med)

    ref_pool = ([r["price"] for r in rows if r["price"] and r["match_type"] == "exact" and not r["suspect"]]
                or [r["price"] for r in rows if r["price"] and not r["suspect"]]
                or [r["price"] for r in rows if r["price"]])
    ref = min(ref_pool) if ref_pool else None
    for r in rows:
        r["_s"]["price"] = min(100.0, 100.0 * ref / r["price"]) if (ref and r["price"]) else 0.0
        s_ = r["_s"]
        r["score"] = round(sum(weights[k] * s_[k] for k in weights) * (0.6 if r["suspect"] else 1.0), 1)

    # ---- flags / warnings (deterministic, data-grounded) ----
    for r in rows:
        if r["price"] is None:
            r["flags"].append("Price not detected - open the store page to confirm")
        elif r["price_source"] == "snippet":
            r["flags"].append("Price read from a search snippet - confirm on the store")
        if r["suspect"]:
            r["flags"].append("Price far below other stores - check authenticity, PTA status and warranty")
        if r["availability"].lower().startswith("out of stock"):
            r["flags"].append("Listed as out of stock")
        if not r["rating"]:
            r["flags"].append("No seller/product rating found")

    rows.sort(key=lambda r: r["score"], reverse=True)
    exact = [r for r in rows if r["match_type"] == "exact"]
    similar = [r for r in rows if r["match_type"] == "similar"]
    pool = [r for r in (exact or rows) if not r["suspect"]] or (exact or rows)
    priced = [r for r in pool if r["price"]]

    summary = {
        "best_value": pool[0] if pool else None,
        "best_price": min(priced, key=lambda r: r["price"]) if priced else None,
        "fastest": min(pool, key=lambda r: (r["delivery_max"], r["price"] or 1e12)) if pool else None,
    }
    missing = [PLATFORMS_BY_KEY[k].name for k in platforms_searched if k not in platforms_with_results]
    return {
        "exact": exact, "similar": similar, "summary": summary,
        "excluded_over_budget": excluded_budget, "platforms_without_results": missing,
        "weights": weights,
    }
