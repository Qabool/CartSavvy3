"""Typed data structures shared by agents, retrieval, scoring and UI."""
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------- LLM structured outputs (kept Gemini-schema friendly: no free-form dicts) ----------
class SearchPlan(BaseModel):
    clean_query: str = Field(description="Normalised English product search phrase, 2-8 words")
    category: Literal["electronics", "grocery", "pharmacy", "fashion", "home", "beauty", "general"]
    brand: str = Field(default="", description="Brand if stated, else empty")
    model_or_variant: str = Field(default="", description="Model number / size / storage if stated")
    must_have: List[str] = Field(default_factory=list, description="Hard requirements from the shopper")
    notes: str = Field(default="", description="One short note about assumptions")


class Attribute(BaseModel):
    name: str
    value: str


class ListingJudgement(BaseModel):
    id: str = Field(description="Listing id exactly as returned by the search tool, e.g. L3")
    match_type: Literal["exact", "similar", "irrelevant"]
    confidence: float = Field(description="0.0-1.0 confidence in the match_type")
    attributes: List[Attribute] = Field(default_factory=list, description="Up to 6 key specs found in the listing text")
    reason: str = Field(default="", description="Max 20 words why exact/similar/irrelevant")


class ResearchOutput(BaseModel):
    judgements: List[ListingJudgement]


class Advice(BaseModel):
    headline: str = Field(description="Max 12 words")
    recommendation: str = Field(description="Max 110 words, plain language")
    warnings: List[str] = Field(default_factory=list)
    follow_ups: List[str] = Field(default_factory=list)


# ---------- Plain python structures ----------
@dataclass
class Listing:
    id: str
    platform_key: str
    platform: str
    title: str
    url: str
    price: Optional[float] = None
    original_price: Optional[float] = None
    price_source: str = ""          # "page" | "snippet" | ""
    availability: str = ""
    brand: str = ""
    rating: Optional[float] = None
    review_count: Optional[int] = None
    image: str = ""
    description: str = ""
    snippet: str = ""
    seller: str = ""
    page_checked: bool = False


@dataclass
class Preferences:
    city: str = "Karachi"
    category: str = "auto"
    budget_max: float = 0.0
    condition: str = "any"
    platform_keys: list = field(default_factory=list)
    per_platform: int = 3
    priority: str = "balanced"
    deadline_days: int = 0
    prefer_cod: bool = False
