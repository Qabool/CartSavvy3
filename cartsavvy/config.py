"""Static configuration: stores, cities and scoring presets.

Delivery times, payment methods and trust priors below are TYPICAL values taken
from each store's general policy. They are shown to users as estimates, never as
live guarantees. Edit freely as you validate each store.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

METRO_CITIES = {"Karachi", "Lahore", "Islamabad", "Rawalpindi"}
CITIES = [
    "Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad", "Multan",
    "Peshawar", "Hyderabad", "Quetta", "Sialkot", "Gujranwala", "Other city",
]
CATEGORIES = ["electronics", "grocery", "pharmacy", "fashion", "home", "beauty", "general"]
MAX_PLATFORMS = 7  # cap parallel store searches (keeps search backend happy)

GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
DEFAULT_MODEL = GEMINI_MODELS[0]

_ALL = tuple(CATEGORIES)


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    domain: str
    categories: Tuple[str, ...]
    metro_days: Tuple[int, int] = (2, 4)
    other_days: Tuple[int, int] = (3, 6)
    metro_label: str = ""
    payments: Tuple[str, ...] = ("COD", "Card", "Bank transfer")
    trust: float = 0.75  # baseline reliability prior (0-1)


PLATFORMS: List[Platform] = [
    Platform("daraz", "Daraz", "daraz.pk", _ALL, (2, 4), (3, 7), "", ("COD", "Card", "Wallet", "Installments"), 0.85),
    Platform("telemart", "Telemart", "telemart.pk", ("electronics",), (2, 4), (3, 6), "", ("COD", "Card", "Bank transfer", "Installments"), 0.80),
    Platform("shophive", "Shophive", "shophive.com", ("electronics",), (2, 4), (3, 6), "", ("COD", "Card", "Bank transfer", "Installments"), 0.80),
    Platform("homeshopping", "Homeshopping", "homeshopping.pk", ("electronics", "home", "general"), (2, 4), (3, 6), "", ("COD", "Card", "Bank transfer"), 0.78),
    Platform("priceoye", "PriceOye", "priceoye.pk", ("electronics",), (2, 4), (3, 6), "", ("COD", "Card"), 0.78),
    Platform("czone", "Czone", "czone.com.pk", ("electronics",), (2, 4), (3, 6), "", ("COD", "Card", "Bank transfer"), 0.75),
    Platform("mega", "Mega.pk", "mega.pk", ("electronics",), (2, 4), (3, 6), "", ("COD", "Card", "Bank transfer"), 0.72),
    Platform("yayvo", "Yayvo", "yayvo.com", ("home", "fashion", "beauty", "general", "electronics"), (3, 5), (4, 7), "", ("COD", "Card"), 0.70),
    Platform("naheed", "Naheed", "naheed.pk", ("grocery", "home", "beauty"), (1, 3), (3, 6), "", ("COD", "Card"), 0.80),
    Platform("alfatah", "Al-Fatah", "alfatah.com.pk", ("grocery", "home"), (1, 3), (3, 6), "", ("COD", "Card"), 0.78),
    Platform("metro", "Metro Online", "metro-online.pk", ("grocery", "home"), (1, 3), (3, 6), "", ("COD", "Card"), 0.78),
    Platform("foodpanda", "Foodpanda (Pandamart)", "foodpanda.pk", ("grocery", "beauty"), (0, 0), (0, 1), "~30-60 min (Pandamart)", ("COD", "Card", "Wallet"), 0.82),
    Platform("dvago", "Dvago", "dvago.pk", ("pharmacy", "beauty"), (0, 2), (2, 5), "", ("COD", "Card", "Wallet"), 0.80),
    Platform("sehat", "Sehat.com.pk", "sehat.com.pk", ("pharmacy", "beauty"), (1, 3), (3, 6), "", ("COD", "Card"), 0.74),
    Platform("khaadi", "Khaadi", "khaadi.com", ("fashion",), (2, 5), (3, 7), "", ("COD", "Card"), 0.80),
    Platform("sapphire", "Sapphire", "pk.sapphireonline.pk", ("fashion",), (2, 5), (3, 7), "", ("COD", "Card"), 0.80),
    Platform("outfitters", "Outfitters", "outfitters.com.pk", ("fashion",), (2, 5), (3, 7), "", ("COD", "Card"), 0.78),
]
PLATFORMS_BY_KEY: Dict[str, Platform] = {p.key: p for p in PLATFORMS}


def select_platforms(category: str) -> List[str]:
    """Pick the most relevant stores for a category (most trusted first)."""
    cat = category if category in CATEGORIES else "general"
    chosen = [p for p in PLATFORMS if cat in p.categories]
    chosen.sort(key=lambda p: p.trust, reverse=True)
    return [p.key for p in chosen[:MAX_PLATFORMS]]


def delivery_estimate(p: Platform, city: str) -> Tuple[int, int, str]:
    metro = city in METRO_CITIES
    lo, hi = p.metro_days if metro else p.other_days
    if metro and p.metro_label:
        label = p.metro_label
    elif hi == 0:
        label = "Same day"
    elif lo == hi:
        label = f"{hi} days"
    else:
        label = f"{lo}-{hi} days"
    return lo, hi, label


# Best-value score weights (must sum to 1.0) - mirrors the product specification
WEIGHT_PRESETS: Dict[str, Dict[str, float]] = {
    "balanced":     {"price": 0.35, "delivery": 0.20, "trust": 0.20, "warranty": 0.10, "match": 0.10, "payment": 0.05},
    "lowest_price": {"price": 0.55, "delivery": 0.10, "trust": 0.15, "warranty": 0.05, "match": 0.10, "payment": 0.05},
    "fastest":      {"price": 0.20, "delivery": 0.45, "trust": 0.15, "warranty": 0.05, "match": 0.10, "payment": 0.05},
    "most_trusted": {"price": 0.20, "delivery": 0.10, "trust": 0.40, "warranty": 0.15, "match": 0.10, "payment": 0.05},
}
PRESET_LABELS = {
    "balanced": "Best overall value",
    "lowest_price": "Lowest price",
    "fastest": "Fastest delivery",
    "most_trusted": "Most trusted seller",
}
