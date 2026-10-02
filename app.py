"""CartSavvy - Streamlit front-end. Run locally with:  streamlit run app.py"""
import os

# Silence CrewAI telemetry / tracing prompts BEFORE importing crewai (important on Streamlit Cloud)
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
LOGO = ROOT / "assets" / "logo_cropped.png"
FAVICON = ROOT / "assets" / "favicon.png"

st.set_page_config(
    page_title="CartSavvy | Compare smart. Buy right.",
    page_icon=str(FAVICON) if FAVICON.exists() else "\U0001F6D2",
    layout="wide",
    initial_sidebar_state="expanded",
)

from cartsavvy import ui  # noqa: E402
from cartsavvy.config import (  # noqa: E402
    CATEGORIES, CITIES, DEFAULT_MODEL, GEMINI_MODELS, PLATFORMS, PRESET_LABELS,
)
from cartsavvy.crew import QuotaError, cached_pipeline  # noqa: E402
from cartsavvy.models import Preferences  # noqa: E402
from cartsavvy.retrieval import self_test  # noqa: E402


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets[name])
    except Exception:  # no secrets file / key missing
        return os.environ.get(name, default)


API_KEY = secret("GEMINI_API_KEY")
if secret("SERPER_API_KEY"):
    os.environ["SERPER_API_KEY"] = secret("SERPER_API_KEY")

ui.inject_css()

# ------------------------------------------------------------------ header
head_l, head_r = st.columns([2, 3])
with head_l:
    if LOGO.exists():
        st.image(str(LOGO), width=280)
    else:
        st.markdown("## CartSavvy")
ui.hero()

# ------------------------------------------------------------------ sidebar
default_model = secret("GEMINI_MODEL", DEFAULT_MODEL)
models = GEMINI_MODELS if default_model in GEMINI_MODELS else [default_model] + GEMINI_MODELS

with st.sidebar:
    st.markdown("### Your preferences")
    city = st.selectbox("Delivery city", CITIES, index=0)
    category = st.selectbox("Category", ["auto"] + CATEGORIES,
                            format_func=lambda c: "Auto-detect" if c == "auto" else c.title())
    budget = st.number_input("Maximum budget (PKR)", min_value=0, step=1000, value=0, help="0 means no limit")
    condition = st.selectbox("Condition", ["any", "new", "used / refurbished"],
                             format_func=lambda c: c.title())
    priority = st.selectbox("What matters most?", list(PRESET_LABELS), format_func=PRESET_LABELS.get)
    deadline = st.selectbox("Needed within", [0, 2, 3, 5, 7],
                            format_func=lambda d: "No deadline" if d == 0 else f"{d} days")
    prefer_cod = st.checkbox("Prefer cash on delivery")
    with st.expander("Advanced"):
        chosen = st.multiselect("Stores (empty = automatic)", [p.key for p in PLATFORMS],
                                format_func=lambda k: next(p.name for p in PLATFORMS if p.key == k))
        per_platform = st.slider("Listings per store", 1, 4, 3)
        model = st.selectbox("Gemini model", models, index=models.index(default_model))
        fresh = st.checkbox("Skip 30-minute cache", help="Forces a fresh search (uses more free-tier quota)")
    if st.button("Run connection test"):
        with st.spinner("Testing search and store access..."):
            for line in self_test():
                st.text(line)
    st.caption("Delivery times and payment methods are typical store policies, not live quotes. "
               "Always confirm on the store page before paying.")

prefs = Preferences(
    city=city, category=category, budget_max=float(budget), condition=condition,
    platform_keys=chosen, per_platform=per_platform, priority=priority,
    deadline_days=int(deadline), prefer_cod=prefer_cod,
)

# ------------------------------------------------------------------ search form
EXAMPLES = ["Samsung Galaxy A55 128GB", "Dell Inspiron 15 laptop", "Dalda cooking oil 5 litre", "Panadol 500mg"]


def _use_example(text: str) -> None:
    st.session_state["q"] = text
    st.session_state["auto_run"] = True


with st.form("search", border=False):
    c1, c2 = st.columns([5, 1])
    query = c1.text_input("What are you looking for?", key="q",
                          placeholder="e.g. Samsung A55 128GB, ya  'sasta laptop for students'",
                          label_visibility="collapsed")
    submitted = c2.form_submit_button("Compare prices", type="primary")

ex_cols = st.columns(len(EXAMPLES))
for col, ex in zip(ex_cols, EXAMPLES):
    col.button(ex, key=f"ex_{ex}", on_click=_use_example, args=(ex,))

run = submitted or st.session_state.pop("auto_run", False)

if run:
    q = (st.session_state.get("q") or "").strip()
    if len(q) < 2:
        st.warning("Please type a product to search for.")
    elif not API_KEY:
        st.error("GEMINI_API_KEY is missing. Add it in Streamlit Cloud > App settings > Secrets "
                 "(or in .streamlit/secrets.toml when running locally).")
    else:
        with st.status("CartSavvy agents are working...", expanded=True) as status:
            try:
                st.session_state["result"] = cached_pipeline(
                    q, prefs, API_KEY, model, progress=lambda m: status.write(m), force=fresh)
                status.update(label="Comparison ready", state="complete", expanded=False)
            except QuotaError:
                status.update(label="Gemini free-tier limit reached", state="error")
                st.error("The Gemini free-tier rate or daily limit was reached. Wait a minute and retry, switch to "
                         "'gemini-3.5-flash-lite' (higher daily quota) under Advanced, or enable billing in Google AI Studio.")
            except Exception as exc:  # noqa: BLE001
                status.update(label="Something went wrong", state="error")
                st.error(f"Search failed: {exc}")

# ------------------------------------------------------------------ results
res = st.session_state.get("result")
if not res:
    with st.expander("How CartSavvy works", expanded=True):
        st.markdown(
            "1. **Query Strategist agent** understands your request (English, Urdu or Roman Urdu).\n"
            "2. **Market Researcher agent** searches trusted Pakistani stores in parallel and judges every listing as exact, similar or irrelevant.\n"
            "3. **Scoring engine** ranks offers by price, delivery, seller trust, warranty, match quality and payment options.\n"
            "4. **Value Advisor agent** explains the best choice, with a direct link to each product page."
        )
else:
    scored, advice, meta = res["scored"], res["advice"], res["meta"]
    st.markdown(f"#### Results for *{res['query']}*")
    ui.summary_cards(scored["summary"])
    ui.advice_box(advice)

    exact, similar = scored["exact"], scored["similar"]
    tab_best, tab_table, tab_alt, tab_info = st.tabs(
        [f"Best matches ({len(exact)})", "Comparison table", f"Similar alternatives ({len(similar)})", "Insights"])

    with tab_best:
        if exact:
            ui.card_grid(exact[:9], scored["summary"])
        elif similar:
            st.info("No exact matches were found. Showing the closest alternatives instead.")
            ui.card_grid(similar[:9], scored["summary"])
        else:
            st.warning("No comparable listings were found. Try a simpler product name, remove the budget limit, "
                       "or select more stores under Advanced. Adding a SERPER_API_KEY secret improves coverage.")
            with st.expander("Why? Search diagnostics", expanded=True):
                for line in meta.get("diagnostics", []) or ["No diagnostics recorded."]:
                    st.text(line)

    with tab_table:
        rows = exact + similar
        if rows:
            df = ui.to_dataframe(rows)
            ui.show_table(df)
            st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"),
                               file_name="cartsavvy_comparison.csv", mime="text/csv")
        else:
            st.write("Nothing to compare yet.")

    with tab_alt:
        if similar:
            ui.card_grid(similar[:9], scored["summary"])
        else:
            st.write("No similar alternatives found.")

    with tab_info:
        for f in advice.get("follow_ups", []):
            st.markdown(f"- Try: *{f}*")
        if scored["platforms_without_results"]:
            st.markdown("**Stores with no usable results:** " + ", ".join(scored["platforms_without_results"]))
        if scored["excluded_over_budget"]:
            st.markdown(f"**{scored['excluded_over_budget']} listing(s)** were hidden because they exceed your budget.")
        with st.expander("Search diagnostics"):
            for line in meta.get("diagnostics", []):
                st.text(line)
        st.markdown("**Search plan (from the Strategist agent)**")
        st.json(res["plan"], expanded=False)
        st.caption(
            f"Model: {meta['model']} | Stores: {', '.join(meta['stores_searched']) or 'n/a'} | "
            f"Listings found: {meta['listings_found']} | Time: {meta['seconds']}s | "
            f"{'Served from cache | ' if meta.get('from_cache') else ''}Generated {meta['generated_at']}")

st.divider()
st.caption("CartSavvy is an independent comparison tool and is not affiliated with any listed store. Prices, stock and "
           "delivery estimates can change at any time - verify on the store page before you buy. Some links may become "
           "affiliate links in the future and will be clearly disclosed.")
