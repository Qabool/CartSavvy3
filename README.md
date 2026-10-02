# CartSavvy - Compare smart. Buy right.

An agentic AI shopping assistant for Pakistan. Type a product, and CartSavvy's CrewAI agents search trusted
stores (Daraz, Telemart, Shophive, Homeshopping, PriceOye, Czone, Mega.pk, Naheed, Metro, Foodpanda/Pandamart,
Dvago, Sehat and more), compare price, delivery, warranty and seller trust, and link you to each product page.

**Stack:** Python 3.11-3.13 - CrewAI 1.15.x - Google Gemini (free tier) - Streamlit 1.5x/1.6x

## Architecture

```
User query -> Streamlit UI
   Stage 1 crew
     1. Query Strategist agent  -> SearchPlan (clean query, category, brand, model)
     2. Market Researcher agent -> "Marketplace search" tool (parallel, per store)
                                   -> judges each listing: exact / similar / irrelevant
   Scoring engine (pure Python)  -> best-value score, flags, price-outlier warnings
   Stage 2 crew
     3. Value Advisor agent     -> plain-language recommendation grounded in the ranked table
```

Design rules that keep it trustworthy: prices, links, and delivery windows come from code (never from the LLM);
the LLM only references listings by id; every number shown is traceable to retrieved data.
A fresh search costs about 5-6 Gemini calls; results are cached for 30 minutes to save quota.

## Repository layout

```
app.py                      Streamlit UI
requirements.txt
.streamlit/config.toml      Theme (matches logo colours)
.streamlit/secrets.toml.example
assets/                     logo.png, logo_cropped.png, favicon.png
cartsavvy/
  config.py                 Store registry, cities, scoring weights, Gemini model list
  models.py                 Pydantic schemas + dataclasses
  retrieval.py              Site-restricted search + product-page parsing (JSON-LD / OpenGraph)
  scoring.py                Deterministic ranking and warnings
  crew.py                   CrewAI agents, tool, pipeline, TTL cache
  ui.py                     Branded CSS + HTML cards
```

## Deploy on Streamlit Community Cloud

1. Create a GitHub repo and upload everything in this folder (do NOT upload `.streamlit/secrets.toml`).
2. Go to share.streamlit.io, choose **Create app**, pick the repo, branch `main`, main file `app.py`.
3. Open **Advanced settings** and select **Python 3.12** (CrewAI requires 3.10-3.13).
4. Paste into **Secrets**:
   ```toml
   GEMINI_API_KEY = "your-google-ai-studio-key"
   GEMINI_MODEL   = "gemini-3.5-flash-lite"
   SERPER_API_KEY = ""   # optional
   ```
5. Deploy. The first build takes a few minutes because CrewAI is a large dependency.

Get a free Gemini key at https://aistudio.google.com/apikey.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then add your key
streamlit run app.py
```

## Free-tier notes (as of Sept 2026)

- `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`: about 500 requests/day -> roughly 80-100 searches/day.
- `gemini-3.8-flash`: smarter but only about 20 requests/day on the free tier -> 3-4 searches/day.
- Limits change; check https://ai.google.dev/gemini-api/docs/rate-limits and edit `GEMINI_MODELS` in `cartsavvy/config.py`.

## Known limitations (please read)

- **Data access is the hard part.** Most Pakistani stores have no public product API. This MVP reads public
  search results and public product-page metadata only. Some stores (notably large marketplaces) block
  datacenter IPs, so prices may come from search snippets or be missing; the UI flags these clearly.
- **Respect each store's Terms of Service and robots.txt.** For production, pursue affiliate programs and partner feeds,
  and replace `retrieval.py` with official connectors (same `Listing` structure, nothing else changes).
- **Delivery, payment options and trust priors are typical values** in `config.py`, not live data.
- **Verify store domains** in `config.py` before launch, and add or remove stores freely.
- Get a Pakistani legal opinion before commercial launch (scraping, affiliate disclosure, data protection).

## Troubleshooting

| Symptom | Fix |
|---|---|
| "GEMINI_API_KEY is missing" | Add it in app Secrets and reboot the app |
| Quota / 429 error | Wait a minute, use a flash-lite model, or enable billing in AI Studio |
| No results | Simplify the query, add `SERPER_API_KEY`, or select stores manually |
| Build fails on dependencies | Choose Python 3.12; then pin versions from `pip freeze` |
| Model not found | Update `GEMINI_MODELS` with a current model id from Google AI Studio |

## Roadmap

Price-history & alerts - official store connectors / affiliate feeds - Urdu UI - image/barcode search - WhatsApp bot.

## Diagnosing "No comparable listings were found"

1. Open the sidebar and press **Run connection test**. It shows whether web search and the stores are reachable from your Streamlit server.
2. Search again and open **Why? Search diagnostics** (or Insights > Search diagnostics) to see what each store returned.
3. If search returns nothing, the free DuckDuckGo backend is likely blocked or rate-limited from the cloud server: add a free `SERPER_API_KEY` secret (serper.dev).
