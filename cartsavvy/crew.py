"""CrewAI orchestration for CartSavvy.

Pipeline (5-6 Gemini calls per fresh search - friendly to the free tier):
  Stage 1 crew  : Query Strategist  -> SearchPlan
                  Market Researcher -> calls the `Marketplace search` tool, judges every listing
  Python        : deterministic scoring/ranking (prices, links, delivery never come from the LLM)
  Stage 2 crew  : Value Advisor     -> plain-language recommendation grounded in the ranked table
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool
from pydantic import BaseModel

from .config import CATEGORIES, PLATFORMS_BY_KEY, PRESET_LABELS, select_platforms
from .models import Advice, Listing, ListingJudgement, Preferences, ResearchOutput, SearchPlan
from .retrieval import gather
from .scoring import score_results

T = TypeVar("T", bound=BaseModel)


class QuotaError(RuntimeError):
    """Raised when the Gemini free-tier quota / rate limit is hit."""


# ----------------------------------------------------------------------------- helpers
def _safe(text: str) -> str:
    """CrewAI treats {braces} in task text as template variables - neutralise user text."""
    return str(text).replace("{", "(").replace("}", ")").strip()


def build_llm(model: str, api_key: str) -> LLM:
    name = model if model.startswith("gemini/") else f"gemini/{model}"
    temperature = 1.0 if "gemini-3" in name else 0.2  # Gemini 3 family recommends 1.0
    return LLM(model=name, api_key=api_key, temperature=temperature)


def _coerce(task_output: Any, model: Type[T]) -> Optional[T]:
    obj = getattr(task_output, "pydantic", None)
    if isinstance(obj, model):
        return obj
    raw = (getattr(task_output, "raw", "") or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()
    candidates = [raw]
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        candidates.append(m.group(0))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return model.model_validate_json(candidate)
        except Exception:
            continue
    return None


def _is_quota(err: Exception) -> bool:
    s = str(err).lower()
    return any(k in s for k in ("429", "resource_exhausted", "quota", "rate limit", "rate_limit"))


_STOP = {"the", "a", "an", "for", "and", "with", "in", "of", "to", "buy", "price", "online", "pakistan", "new"}


def heuristic_judgements(listings: List[Listing], query: str) -> Dict[str, ListingJudgement]:
    """Keyword-overlap fallback used when the LLM did not judge a listing (or rejected everything)."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1 and t not in _STOP]
    if not tokens:
        tokens = [query.lower()]
    numeric = [t for t in tokens if any(c.isdigit() for c in t)]
    accessories = [w for w in ("case", "cover", "protector", "charger", "cable", "strap", "skin", "holder", "stand") if w not in query.lower()]
    out: Dict[str, ListingJudgement] = {}
    for l in listings:
        text = f"{l.title} {l.url}".lower()
        hit = sum(1 for t in tokens if t in text)
        ratio = hit / len(tokens)
        nums_ok = all(t in text for t in numeric)
        if any(re.search(rf"\b{w}s?\b", l.title.lower()) for w in accessories):
            mt = "irrelevant"
        elif ratio >= 0.8 and nums_ok:
            mt = "exact"
        elif ratio >= 0.4:
            mt = "similar"
        else:
            mt = "irrelevant"
        out[l.id] = ListingJudgement(id=l.id, match_type=mt, confidence=round(min(0.9, ratio), 2),
                                     attributes=[], reason="Matched by keyword overlap with your query")
    return out


class ListingStore:
    """Holds the real retrieved listings so the LLM can only reference them by id."""

    def __init__(self) -> None:
        self.items: Dict[str, Listing] = {}
        self.calls = 0
        self.searched_keys: List[str] = []
        self.diag: List[str] = []
        self._n = 0

    def add(self, listings: List[Listing]) -> None:
        for l in listings:
            self._n += 1
            l.id = f"L{self._n}"
            self.items[l.id] = l


def make_search_tool(store: ListingStore, prefs: Preferences, say: Callable[[str], None]):
    @tool("Marketplace search")
    def marketplace_search(search_query: str, category: str = "general") -> str:
        """Search trusted Pakistani online stores (Daraz, Telemart, Shophive, Dvago, Naheed, etc.)
        for a product. Input: a short English product phrase and a category (electronics, grocery,
        pharmacy, fashion, home, beauty, general). Returns a JSON list of real listings; each has an
        'id' that must be used when judging results."""
        store.calls += 1
        if store.calls > 2:
            return "Search limit reached. Judge the listings you already received."
        cat = prefs.category if prefs.category != "auto" else (category or "general").lower()
        cat = cat if cat in CATEGORIES else "general"
        keys = list(prefs.platform_keys) or select_platforms(cat)
        store.searched_keys = list(dict.fromkeys(store.searched_keys + keys))
        names = ", ".join(PLATFORMS_BY_KEY[k].name for k in keys)
        say(f"Searching {len(keys)} stores in parallel: {names}")
        listings = gather(_safe(search_query), keys, prefs.per_platform, diag=store.diag)
        store.add(listings)
        say(f"Collected {len(listings)} candidate listings - checking prices and details")
        if not listings:
            return "NO_RESULTS"
        compact = [{
            "id": l.id, "store": l.platform, "title": l.title[:140],
            "price_pkr": l.price, "availability": l.availability or None,
            "rating": l.rating, "snippet": (l.description or l.snippet)[:200],
        } for l in listings if l.id in store.items]
        return json.dumps(compact, ensure_ascii=False)

    return marketplace_search


# ----------------------------------------------------------------------------- stages
def _stage1(llm: LLM, query: str, prefs: Preferences, store: ListingStore, say) -> Dict[str, Any]:
    strategist = Agent(
        role="Pakistan Shopping Query Strategist",
        goal="Turn a shopper's request (English, Urdu or Roman Urdu) into a precise product search plan.",
        backstory="You know Pakistani retail: PTA-approved phones, Roman Urdu spellings, local brands and pack sizes.",
        llm=llm, allow_delegation=False, verbose=False, max_iter=3,
    )
    researcher = Agent(
        role="Pakistan E-commerce Market Researcher",
        goal="Find the same or closest products across reputable Pakistani stores and judge each listing honestly.",
        backstory="A meticulous analyst who only reports facts visible in the retrieved listing data and never invents ids, prices or links.",
        tools=[make_search_tool(store, prefs, say)],
        llm=llm, allow_delegation=False, verbose=False, max_iter=4,
    )

    hints = [f"Delivery city: {prefs.city}"]
    if prefs.budget_max:
        hints.append(f"Budget limit: Rs. {prefs.budget_max:,.0f}")
    if prefs.condition != "any":
        hints.append(f"Condition: {prefs.condition}")
    if prefs.category != "auto":
        hints.append(f"Category forced by user: {prefs.category}")

    t1 = Task(
        description=(
            f"Shopper request: \"{_safe(query)}\"\n" + "\n".join(hints) + "\n\n"
            "Create a search plan: a clean English product phrase (keep brand, model, size/storage), the best "
            "category, brand, model/variant, and any must-have requirements. Do not add features the shopper did not ask for."
        ),
        expected_output="A SearchPlan object.",
        agent=strategist, output_pydantic=SearchPlan,
    )
    t2 = Task(
        description=(
            "Use the search plan from the previous task. Call the 'Marketplace search' tool ONCE with the plan's "
            "clean_query and category. The tool returns real listings, each with an id.\n"
            "Then return exactly one judgement per listing id:\n"
            "- exact: same product (brand + model/variant/size) as requested\n"
            "- similar: a reasonable alternative in the same product class\n"
            "- irrelevant: accessory, wrong product, category/blog page, or unrelated\n"
            "Give confidence 0-1, up to 6 key attributes (name/value) that appear in the listing text, and a reason of at most 20 words. "
            "Use only ids and facts present in the tool output. If the tool returns NO_RESULTS, return an empty judgements list."
        ),
        expected_output="A ResearchOutput object with one judgement per listing id.",
        agent=researcher, context=[t1], output_pydantic=ResearchOutput,
    )

    done = {"n": 0}

    def on_task(_out: Any) -> None:
        done["n"] += 1
        if done["n"] == 1:
            say("Strategist finished the search plan")
        elif done["n"] == 2:
            say("Researcher finished judging listings")

    crew = Crew(agents=[strategist, researcher], tasks=[t1, t2], process=Process.sequential,
                verbose=False, max_rpm=10, task_callback=on_task)
    say("Strategist agent is interpreting your request")
    res = crew.kickoff()
    outs = list(getattr(res, "tasks_output", []) or [])
    plan = _coerce(outs[0], SearchPlan) if len(outs) > 0 else None
    research = _coerce(outs[1], ResearchOutput) if len(outs) > 1 else None
    return {"plan": plan, "research": research}


def _advice_stage(llm: LLM, query: str, prefs: Preferences, scored: Dict[str, Any]) -> Optional[Advice]:
    pool = (scored["exact"] or scored["similar"])[:6]
    lines = []
    for r in pool:
        price = f"Rs. {r['price']:,.0f}" if r["price"] else "price not found"
        lines.append(f"- {r['platform']} | {price} | delivery ~{r['delivery_label']} | warranty: {r['warranty']} | "
                     f"rating: {r['rating'] or 'n/a'} | {r['match_type']} | score {r['score']:.0f}/100"
                     + (f" | flags: {'; '.join(r['flags'])}" if r["flags"] else ""))
    advisor = Agent(
        role="Value Advisor for Pakistani Online Shoppers",
        goal="Explain the best choice clearly and honestly using only the numbers provided.",
        backstory="A consumer-protection minded advisor. You never quote a number that is not in the table and you flag uncertainty.",
        llm=llm, allow_delegation=False, verbose=False, max_iter=2,
    )
    task = Task(
        description=(
            f"Shopper request: \"{_safe(query)}\" | city: {prefs.city} | priority: {PRESET_LABELS.get(prefs.priority, prefs.priority)}"
            + (f" | budget: Rs. {prefs.budget_max:,.0f}" if prefs.budget_max else "") + "\n\n"
            "Ranked offers (already scored by software - do not re-rank):\n" + "\n".join(lines) + "\n\n"
            "Write: a short headline, a recommendation (max 110 words) that names the best overall pick, the cheapest, and the fastest "
            "if they differ, up to 3 plain-language warnings (e.g. snippet-only prices, missing warranty, delivery being an estimate), "
            "and up to 3 follow-up refinements the shopper could ask for. Use only the figures above."
        ),
        expected_output="An Advice object.", agent=advisor, output_pydantic=Advice,
    )
    res = Crew(agents=[advisor], tasks=[task], process=Process.sequential, verbose=False, max_rpm=10).kickoff()
    outs = list(getattr(res, "tasks_output", []) or [])
    return _coerce(outs[0], Advice) if outs else None


def _fallback_advice(scored: Dict[str, Any]) -> Dict[str, Any]:
    s = scored["summary"]
    if not s["best_value"]:
        return {"headline": "No comparable listings found", "recommendation":
                "Try a simpler product name, remove filters, or widen the store selection.", "warnings": [], "follow_ups": []}
    bv, bp, fs = s["best_value"], s["best_price"], s["fastest"]
    text = f"{bv['platform']} has the best overall value score ({bv['score']:.0f}/100)."
    if bp:
        text += f" The lowest price found is Rs. {bp['price']:,.0f} at {bp['platform']}."
    if fs:
        text += f" {fs['platform']} offers the fastest typical delivery ({fs['delivery_label']})."
    return {"headline": "Best options found across Pakistani stores", "recommendation": text,
            "warnings": ["Delivery times are typical estimates, not live quotes."], "follow_ups": []}


# ----------------------------------------------------------------------------- public API
def run_pipeline(query: str, prefs: Preferences, api_key: str, model: str,
                 progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    say = progress or (lambda _m: None)
    t0 = time.time()
    llm = build_llm(model, api_key)
    store = ListingStore()

    try:
        s1 = _stage1(llm, query, prefs, store, say)
    except Exception as e:  # noqa: BLE001
        if _is_quota(e):
            raise QuotaError(str(e)) from e
        raise

    plan: SearchPlan = s1["plan"] or SearchPlan(clean_query=_safe(query), category="general")
    store.diag.append(f"agent tool calls: {store.calls} | plan parsed: {bool(s1['plan'])} | "
                      f"judgements parsed: {len(s1['research'].judgements) if s1['research'] else 0}")

    # Safety net 1: the agent never called the tool (or it found nothing) -> run the retrieval directly.
    if not store.items:
        say("Agents returned no listings - running a direct store search")
        cat = prefs.category if prefs.category != "auto" else plan.category
        keys = list(prefs.platform_keys) or select_platforms(cat)
        store.searched_keys = list(dict.fromkeys(store.searched_keys + keys))
        store.add(gather(plan.clean_query or _safe(query), keys, prefs.per_platform, diag=store.diag))

    judgements = {j.id: j for j in (s1["research"].judgements if s1["research"] else []) if j.id in store.items}
    # Safety net 2: listings the LLM did not judge get a keyword-overlap judgement.
    missing = [l for l in store.items.values() if l.id not in judgements]
    if missing:
        judgements.update(heuristic_judgements(missing, plan.clean_query or query))

    say("Scoring and ranking offers")
    scored = score_results(store.items.values(), judgements, prefs, store.searched_keys)
    # Safety net 3: the LLM rejected everything -> trust keyword overlap instead.
    if store.items and not (scored["exact"] or scored["similar"]):
        store.diag.append("LLM marked every listing irrelevant - re-judged by keyword overlap")
        scored = score_results(store.items.values(), heuristic_judgements(list(store.items.values()), plan.clean_query or query),
                               prefs, store.searched_keys)

    advice: Dict[str, Any]
    if scored["exact"] or scored["similar"]:
        say("Value Advisor is writing your recommendation")
        try:
            adv = _advice_stage(llm, query, prefs, scored)
            advice = adv.model_dump() if adv else _fallback_advice(scored)
        except Exception as e:  # noqa: BLE001
            if _is_quota(e):
                advice = _fallback_advice(scored)  # keep the results even if quota ran out at the last step
                advice["warnings"].append("AI summary unavailable (quota reached) - showing computed results.")
            else:
                advice = _fallback_advice(scored)
    else:
        advice = _fallback_advice(scored)

    return {
        "query": query, "plan": plan.model_dump(), "scored": scored, "advice": advice,
        "meta": {"model": model, "seconds": round(time.time() - t0, 1),
                 "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "stores_searched": [PLATFORMS_BY_KEY[k].name for k in store.searched_keys],
                 "listings_found": len(store.items), "diagnostics": store.diag,
                 "llm_calls_note": "approx. 5-6 per fresh search"},
    }


# ----------------------------------------------------------------------------- tiny TTL cache (saves free-tier quota)
_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()
_TTL = 30 * 60


def cached_pipeline(query: str, prefs: Preferences, api_key: str, model: str,
                    progress: Optional[Callable[[str], None]] = None, force: bool = False) -> Dict[str, Any]:
    key = hashlib.sha256(json.dumps([query.strip().lower(), asdict(prefs), model], sort_keys=True, default=str).encode()).hexdigest()
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and not force and now - hit[0] < _TTL:
            out = dict(hit[1])
            out["meta"] = {**out["meta"], "from_cache": True}
            return out
    result = run_pipeline(query, prefs, api_key, model, progress)
    with _LOCK:
        if len(_CACHE) > 100:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (now, result)
    return result
