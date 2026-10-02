"""Presentation helpers: CSS theme (matches the CartSavvy logo) and HTML card renderers."""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

TEAL, GREEN, AMBER = "#0F6E56", "#1D9E75", "#FAC775"

CSS = f"""
<style>
:root {{ --teal:{TEAL}; --green:{GREEN}; --amber:{AMBER}; --ink:#12332B; --muted:#5B7A71; --line:#D5E6E0; --tint:#F1F7F5; }}
.block-container {{ padding-top: 1.6rem; max-width: 1200px; }}
footer {{ visibility: hidden; }}
[data-testid="stSidebar"] {{ background: var(--tint); border-right: 1px solid var(--line); }}
.cs-hero {{ background: linear-gradient(135deg, {TEAL} 0%, #0B5744 100%); color:#fff; border-radius:18px; padding:28px 32px; margin: 8px 0 18px 0; }}
.cs-hero h1 {{ color:#fff; font-size:1.9rem; margin:0 0 6px 0; line-height:1.2; }}
.cs-hero p {{ color:#D7F0E7; margin:0; font-size:1.02rem; }}
.cs-hero .cs-spark {{ color: var(--amber); }}
.cs-pill {{ display:inline-block; background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.25); color:#fff; border-radius:999px; padding:3px 12px; margin:12px 8px 0 0; font-size:.82rem; }}
.cs-sum {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:16px 18px; height:100%; border-top:4px solid var(--green); }}
.cs-sum.amber {{ border-top-color: var(--amber); }} .cs-sum.teal {{ border-top-color: var(--teal); }}
.cs-sum .lbl {{ color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; }}
.cs-sum .val {{ color:var(--teal); font-size:1.55rem; font-weight:700; margin:4px 0 2px 0; }}
.cs-sum .sub {{ color:var(--ink); font-size:.9rem; }}
.cs-advice {{ background: #FFF8EA; border:1px solid {AMBER}; border-left:6px solid {AMBER}; border-radius:12px; padding:16px 20px; margin:16px 0; color:var(--ink); }}
.cs-advice h4 {{ margin:0 0 6px 0; color:var(--teal); }}
.cs-card {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:14px; margin-bottom:14px; transition: box-shadow .15s; }}
.cs-card:hover {{ box-shadow: 0 6px 18px rgba(15,110,86,.12); }}
.cs-top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:6px; }}
.cs-store {{ font-weight:700; color:var(--teal); }}
.cs-badge {{ font-size:.7rem; font-weight:700; border-radius:999px; padding:2px 9px; margin-left:4px; }}
.cs-b-val {{ background:{TEAL}; color:#fff; }} .cs-b-price {{ background:#DDF3EA; color:#0B5744; }} .cs-b-fast {{ background:{AMBER}; color:#412402; }}
.cs-img {{ height:130px; display:flex; align-items:center; justify-content:center; background:var(--tint); border-radius:10px; margin-bottom:10px; overflow:hidden; }}
.cs-img img {{ max-height:126px; max-width:100%; object-fit:contain; }}
.cs-noimg {{ color:#9DB8AF; font-size:.8rem; }}
.cs-title {{ font-size:.92rem; color:var(--ink); min-height:2.5em; line-height:1.25; margin-bottom:6px; }}
.cs-price {{ font-size:1.35rem; font-weight:800; color:var(--teal); }}
.cs-price s {{ font-size:.85rem; font-weight:400; color:#8AA399; margin-left:6px; }}
.cs-disc {{ background:#FFF1D6; color:#7A4B00; font-size:.75rem; font-weight:700; border-radius:6px; padding:1px 6px; margin-left:6px; }}
.cs-meta {{ list-style:none; padding:0; margin:8px 0; font-size:.82rem; color:var(--ink); }}
.cs-meta li {{ padding:2px 0; }} .cs-meta b {{ color:var(--muted); font-weight:600; }}
.cs-chip {{ display:inline-block; background:var(--tint); border:1px solid var(--line); border-radius:8px; font-size:.72rem; padding:1px 7px; margin:0 4px 4px 0; color:var(--ink); }}
.cs-bar {{ height:6px; background:#E3EEEA; border-radius:6px; overflow:hidden; margin:8px 0 10px 0; }}
.cs-bar > div {{ height:100%; background: linear-gradient(90deg, {GREEN}, {TEAL}); }}
.cs-flag {{ font-size:.75rem; color:#7A4B00; background:#FFF8EA; border-radius:6px; padding:3px 7px; margin-bottom:5px; }}
a.cs-btn {{ display:block; text-align:center; background:{TEAL}; color:#fff !important; text-decoration:none; font-weight:600; border-radius:10px; padding:9px 0; }}
a.cs-btn:hover {{ background:{GREEN}; }}
.cs-note {{ color:var(--muted); font-size:.8rem; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero() -> None:
    st.markdown(
        '<div class="cs-hero"><h1>Find the best deal across Pakistan\'s trusted stores <span class="cs-spark">&#10022;</span></h1>'
        "<p>Tell CartSavvy what you want. AI agents compare price, delivery, warranty and seller trust, then link you straight to the product page.</p>"
        '<span class="cs-pill">Compare smart</span><span class="cs-pill">Buy right</span>'
        '<span class="cs-pill">Direct store links</span></div>',
        unsafe_allow_html=True,
    )


def _e(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def money(v: Optional[float]) -> str:
    return f"Rs. {v:,.0f}" if v else "Price n/a"


def summary_cards(summary: Dict[str, Any]) -> None:
    items = [
        ("Best price", "best_price", "", lambda r: money(r["price"])),
        ("Fastest delivery", "fastest", "amber", lambda r: r["delivery_label"]),
        ("Best overall value", "best_value", "teal", lambda r: f"{r['score']:.0f} / 100"),
    ]
    cols = st.columns(3)
    for col, (label, key, css, fmt) in zip(cols, items):
        r = summary.get(key)
        with col:
            if r:
                sub = f"{_e(r['platform'])}" + (f" &middot; {money(r['price'])}" if key != "best_price" and r["price"] else "")
                st.markdown(f'<div class="cs-sum {css}"><div class="lbl">{label}</div><div class="val">{_e(fmt(r))}</div><div class="sub">{sub}</div></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="cs-sum {css}"><div class="lbl">{label}</div><div class="val">-</div><div class="sub">Not available</div></div>', unsafe_allow_html=True)


def advice_box(advice: Dict[str, Any]) -> None:
    warns = "".join(f"<li>{_e(w)}</li>" for w in advice.get("warnings", []))
    st.markdown(
        f'<div class="cs-advice"><h4>{_e(advice.get("headline", ""))}</h4><div>{_e(advice.get("recommendation", ""))}</div>'
        + (f'<ul style="margin:8px 0 0 0;padding-left:18px;font-size:.88rem">{warns}</ul>' if warns else "") + "</div>",
        unsafe_allow_html=True,
    )


def product_card(r: Dict[str, Any], badges: Optional[List[str]] = None) -> str:
    b = "".join(badges or [])
    img = (f'<img src="{_e(r["image"])}" loading="lazy" referrerpolicy="no-referrer" alt="">'
           if str(r.get("image", "")).startswith("http") else '<span class="cs-noimg">No image</span>')
    price = f'<div class="cs-price">{_e(money(r["price"]))}'
    if r.get("original_price") and r.get("price"):
        price += f'<s>{_e(money(r["original_price"]))}</s>'
    if r.get("discount_pct"):
        price += f'<span class="cs-disc">-{r["discount_pct"]}%</span>'
    price += "</div>"
    rating = f"{r['rating']:.1f}/5" + (f" ({r['review_count']})" if r.get("review_count") else "") if r.get("rating") else "n/a"
    chips = "".join(f'<span class="cs-chip">{_e(n)}: {_e(v)}</span>' for n, v in r.get("attributes", [])[:4])
    flags = "".join(f'<div class="cs-flag">{_e(f)}</div>' for f in r.get("flags", [])[:2])
    return (
        f'<div class="cs-card"><div class="cs-top"><span class="cs-store">{_e(r["platform"])}</span><span>{b}</span></div>'
        f'<div class="cs-img">{img}</div><div class="cs-title">{_e(r["title"][:110])}</div>{price}'
        f'<ul class="cs-meta"><li><b>Delivery (est.):</b> {_e(r["delivery_label"])}</li><li><b>Stock:</b> {_e(r["availability"])}</li>'
        f'<li><b>Rating:</b> {_e(rating)}</li><li><b>Warranty:</b> {_e(r["warranty"])}</li>'
        f'<li><b>Payment:</b> {_e(", ".join(r["payments"]))}</li></ul>{chips}'
        f'<div class="cs-bar"><div style="width:{max(2, min(100, r["score"]))}%"></div></div>'
        f'<div class="cs-note" style="margin:-4px 0 8px 0">Best-value score {r["score"]:.0f}/100 &middot; {_e(r["match_type"])} match</div>{flags}'
        f'<a class="cs-btn" href="{_e(r["url"])}" target="_blank" rel="noopener noreferrer">View on {_e(r["platform"])} &#8599;</a></div>'
    )


def card_grid(rows: List[Dict[str, Any]], summary: Dict[str, Any], per_row: int = 3) -> None:
    ids = {k: (v or {}).get("id") for k, v in summary.items()}
    for i in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for col, r in zip(cols, rows[i:i + per_row]):
            badges = []
            if r["id"] == ids.get("best_value"):
                badges.append('<span class="cs-badge cs-b-val">Best value</span>')
            if r["id"] == ids.get("best_price"):
                badges.append('<span class="cs-badge cs-b-price">Lowest price</span>')
            if r["id"] == ids.get("fastest"):
                badges.append('<span class="cs-badge cs-b-fast">Fastest</span>')
            with col:
                st.markdown(product_card(r, badges), unsafe_allow_html=True)
                if r.get("reason") and r["match_type"] == "similar":
                    st.caption(f"Why similar: {r['reason']}")


def to_dataframe(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Rank": i, "Store": r["platform"], "Match": r["match_type"].title(), "Product": r["title"],
        "Price (PKR)": r["price"], "Delivery (est.)": r["delivery_label"], "Stock": r["availability"],
        "Rating": r["rating"], "Warranty": r["warranty"], "Payment": ", ".join(r["payments"]),
        "Score": round(r["score"]), "Link": r["url"],
    } for i, r in enumerate(rows, 1)])


def show_table(df: pd.DataFrame) -> None:
    st.dataframe(
        df, hide_index=True, width="stretch",
        column_config={
            "Price (PKR)": st.column_config.NumberColumn(format="Rs. %d"),
            "Rating": st.column_config.NumberColumn(format="%.1f"),
            "Score": st.column_config.ProgressColumn("Best-value score", min_value=0, max_value=100, format="%d"),
            "Link": st.column_config.LinkColumn("Open", display_text="Open"),
        },
    )
