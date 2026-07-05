# Florida Foreclosure Auction Analysis & Ranking Tool

A decision-support dashboard for a real-estate investor bidding at Florida
county foreclosure/tax-deed auctions. It aggregates upcoming auction
listings, scores/ranks properties against configurable investment criteria,
and presents everything in one dashboard.

**This tool assists research only. It does NOT replace a real title search
or attorney review before bidding.**

## Stack

- Backend: Python 3, FastAPI, SQLAlchemy, SQLite, APScheduler
- Frontend: React + Vite
- Scraping: `requests` + `BeautifulSoup`, per-county adapters

## Quick start

### Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate   # or use system python3
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in any keys you have; all optional
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

On first startup the app will:
- create the SQLite DB (`backend/data/foreclosure.db`)
- seed default score weights
- load `config/counties.yaml` into the `counties` table
- seed a small set of clearly-labeled DEMO properties (see "Data provenance" below)
- register a daily 03:00 APScheduler job that re-scrapes all counties

Verify it's alive:
```bash
curl http://localhost:8000/api/counties
curl http://localhost:8000/api/properties
```

### Frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, talks to backend on :8000
# or: npm run build && npm run preview
```

## Adding/removing counties

Edit `config/counties.yaml` — no code changes needed. Each entry:

```yaml
- county: Hillsborough
  region: Tampa Bay
  platform: realforeclose      # realforeclose | realtaxdeed | grantstreet_clerkauction | other | unknown
  portal_url: https://hillsborough.realforeclose.com
  verified: true                # did we confirm this URL live & correct?
  notes: "free text"
```

`platform` determines which scraper adapter (`backend/scrapers/*.py`) is
used. Restart the backend (or call `POST /api/scrape/all`) after editing.

## County portal research (as of 2026-07-05)

All 14 target counties (Tampa Bay: Hillsborough, Pinellas, Pasco, Hernando,
Manatee, Sarasota; Central FL: Orange, Osceola, Seminole, Polk, Lake,
Volusia, Brevard, Marion) were researched and, as of 2026-07-05, live-checked
via a real (non-sandboxed) browser session — see `config/counties.yaml` for
the verified URL, platform, and notes per county.

**12 of 14 counties run active mortgage-foreclosure calendars on the
RealAuction platform** (realforeclose.com), including **Seminole**
(`seminole.realforeclose.com` — confirmed live with real scheduled sales;
an earlier note in this file wrongly claimed Seminole used a custom
`webapps.seminoleclerk.org` system, but that was never actually verified
live and was corrected once checked). **Lake and Osceola are the two
exceptions** — their `realforeclose.com` foreclosure calendars both return
"This feature is currently offline," confirmed live; both counties instead
run active **tax deed** sales on `realtaxdeed.com`, which `config/counties.yaml`
now points at for those two.

## Scrapers — what's real, what's stubbed

- `backend/scrapers/base.py` — shared interface: rate limiting, retries
  with backoff, and a `run_scraper_safely()` wrapper that guarantees one
  county's exception (or scrape failure) never crashes a batch job. Every
  attempt is logged to `scrape_logs` (success/failure/error/records_found).
- `backend/scrapers/realauction_playwright.py` — the live adapter for all
  14 counties, every one of which is on the RealAuction platform
  (realforeclose.com for 12 of them, realtaxdeed.com for Pinellas/Hernando's
  primary listing and for Lake/Osceola, which only run tax deed sales there,
  not foreclosures — see the county research section above). All 14
  configs point at the same underlying white-label product. Confirmed via a real
  browser session that RealAuction's auction-item data is injected
  client-side through an internal AJAX handshake that only completes inside
  an actual rendered page (a bare HTTP fetch replay of the same endpoint
  returns nothing) — hence a real headless browser (Playwright/Chromium) is
  required, not a plain `requests.get()`. The adapter extracts case number,
  final judgment/opening bid, parcel ID, address, assessed value, and sale
  date/time from each `div.AUCTION_ITEM` on the listing page; anything not
  shown on that page (plaintiff, liens, taxes owed, HOA balance, bankruptcy,
  flood zone, market value/comps) is left null with an explanatory note
  rather than guessed. Covered by `backend/tests/test_realauction_playwright.py`,
  a unit test suite against real captured field values (money/date parsing,
  label mapping) — passes. The full browser-driving code path could not be
  exercised end-to-end in the Cowork sandbox (no root to install Chromium's
  OS dependencies, and no network route to realforeclose.com either), so a
  live smoke test is still needed once this runs somewhere with real
  Chromium + network access (e.g. the Docker image, which runs
  `playwright install --with-deps chromium`).
- `backend/scrapers/realforeclose.py` — the original plain-HTTP attempt at
  this platform, kept for reference; superseded by
  `realauction_playwright.py` in `main.py`'s `SCRAPER_REGISTRY` since a bare
  HTTP GET cannot see RealAuction's client-side-rendered listing data.
- `backend/scrapers/grantstreet.py` — stub adapter for GrantStreet/
  ClerkAuction-style platforms, same honesty rules (no county currently maps
  to it, since no county in `config/counties.yaml` uses this platform, but
  it's there for extensibility).
- `backend/scrapers/sample_data.py` — demo-data seeder, still used as a
  fallback so the UI has something to show before a county's first real
  scrape runs. Every demo record has `is_demo_data=true`, `raw_scraped_json`
  tagged `{"data_source": "SAMPLE_DEMO_DATA_NOT_REAL"}`, and a `notes` field
  prefixed `[DEMO DATA - NOT REAL]`.
- Any county with no successful scrape shows `last_scraped_at: never` /
  last error in the UI and Counties tab, with a link-out to its real portal
  URL instead of fabricated data.

**Bottom line:** the RealAuction adapter is written and unit-tested against
real, live-captured page structure, and `main.py` now actually upserts
scraped records into the Property table (an earlier gap — scrapes used to
run and log but never write results). It has **not yet been run
end-to-end against the live internet** because of the two sandbox
limitations above; that live verification is the next real milestone,
ideally right after or during the Railway deployment (which has neither
restriction).

## Scoring engine (`backend/scoring.py`)

Composite score = weighted sum of these components. Weights live in the
`score_weights` DB table and are re-weightable via `GET`/`PUT /api/weights`
(also exposed as sliders in the frontend "Score Weights" tab).

| Component | Source | Notes |
|---|---|---|
| `equity_spread` | `market_value - final_judgment` | Always shown as a raw dollar figure; ≥ $200k triggers a strong positive normalized score |
| `absorption_rate` | **placeholder** | No free data source identified; field is `null`, contributes 0 to score, clearly labeled placeholder in code and API/UI |
| `crime_rate` | FBI Crime Data API (`api.usa.gov/crime/fbi/cde`), by zip | Requires `CRIME_DATA_API_KEY`; if unset or the call fails, marked `"unavailable"`, not faked |
| `lien_priority` | derived from `plaintiff_type` / `senior_lien_survives` | HOA-COA plaintiff or a surviving senior lien triggers a **large penalty** (large enough to offset most equity-spread gains) plus a loud UI warning |
| `taxes_owed`, `code_liens`, `hoa_balance` | user/scrape-entered fields | Proportional penalties |
| `flood_zone` | intended: FEMA OpenFEMA/NFHL public API (`fema.gov/about/openfema/api`), no key needed | If a lookup isn't wired up for a given record, shown as `"unknown / verify manually"`, not faked |
| `bankruptcy_flag` | user/scrape-entered | Adds a warning + penalty when true |

## API endpoints

- `GET /api/properties` — filter (county, sale date range, min equity spread,
  plaintiff type, occupancy, flag status), sort, paginate
- `GET /api/properties/{id}` — full detail incl. score breakdown + warnings
- `PUT /api/properties/{id}` — update notes / flag_status / rehab estimate
- `GET /api/counties` — per-county platform, portal URL, last scrape status
- `POST /api/scrape/{county}`, `POST /api/scrape/all`
- `GET /api/scrape-status`
- `GET /api/weights`, `PUT /api/weights`
- `GET /api/export?format=csv|xlsx`
- `POST /api/title-search/{property_id}` — stub; returns `not_configured`
  unless `TITLE_SEARCH_API_KEY` + `TITLE_SEARCH_PROVIDER` are set in `.env`.
  Swappable provider function documented in `main.py`
  (`title_search_provider()`); suggested real providers: DataTree/First
  American, ATTOM Data, or a county recorder API. Never called without a key.

## Frontend

- Dashboard table: sortable/filterable by county, sale date range, min
  equity spread, plaintiff type, occupancy, flag status, score
- Card / focused view toggle (1–2 properties per screen) vs. full table
- Property detail: all fields, generated Zillow (`zillow.com/homes/<addr>_rb/`)
  and Realtor.com links, title-search button, notes textarea, flag/save/
  dismiss buttons
- Red warning banners for HOA/junior-lien, surviving senior lien,
  flood zone, bankruptcy
- CSV/XLSX export button
- Refresh button + "data last updated" per county
- Weight-adjustment sliders (Score Weights tab)

## Environment variables (`.env`, never sent to the frontend)

See `.env.example`:
- `DB_PATH` — optional, path to the SQLite DB file. Blank = local default
  (`backend/data/foreclosure.db`). In production, point this at a mounted
  persistent volume (see "Deploy to Railway" below).
- `TITLE_SEARCH_API_KEY`, `TITLE_SEARCH_PROVIDER` — optional, title search stub
- `CRIME_DATA_API_KEY` — optional, FBI Crime Data API
- `FEMA_API_BASE_URL` — public, no key required
- `PORT` — auto-injected by the hosting platform (Railway, etc.) at
  runtime. Do not set this manually.

## Deploy to Railway

The project root has a multi-stage `Dockerfile` (Node build stage for the
React frontend -> Python slim runtime stage that serves both the API and
the built frontend from one process/port) and a `railway.toml` that pins
Railway's builder to that Dockerfile. In production, FastAPI itself mounts
`frontend/dist` and serves it at `/`, so there's only one service to run.

**1. Create a Railway project**

Either via the dashboard (railway.app -> New Project -> Deploy from GitHub
repo) or the CLI:

```bash
npm install -g @railway/cli   # if you don't have it
railway login
cd foreclosure-app
railway init
```

**2. Add a persistent Volume for the SQLite DB**

SQLite writes to a file on disk, and Railway's default filesystem is
ephemeral (wiped on redeploy/restart) — you need a Volume or every deploy
loses your data.

In the Railway dashboard: open your service -> **Volumes** tab -> **New
Volume** -> mount path `/data`. (Any path works; `/data` is just a
common convention.)

**3. Set environment variables**

In the Railway dashboard, under your service's **Variables** tab, set:

- `DB_PATH=/data/foreclosure.db` — must live inside the Volume's mount
  path from step 2, or it won't persist.
- `TITLE_SEARCH_API_KEY` — optional, only if you have a real provider key.
- `TITLE_SEARCH_PROVIDER` — optional, pairs with the key above.
- `CRIME_DATA_API_KEY` — optional, FBI Crime Data API key.
- `FEMA_API_BASE_URL` — optional, defaults to the public FEMA endpoint.

Do **not** set `PORT` — Railway injects it automatically, and the
Dockerfile's `CMD` already reads it (`uvicorn main:app --host 0.0.0.0
--port ${PORT:-8000}`).

**4. Deploy**

Via CLI from the project root:

```bash
railway up
```

Or connect the GitHub repo in the Railway dashboard for auto-deploy on
push. Either way, Railway builds the root `Dockerfile` (thanks to
`railway.toml`'s `builder = "DOCKERFILE"`) and starts the container.

**5. APScheduler tradeoff (daily scrape job)**

The app registers a daily 03:00 scrape-all job via APScheduler inside the
same FastAPI process (see `backend/main.py`, `on_startup`). Two ways to
run this on Railway:

- **Same process as the web service (current setup, recommended to
  start):** simplest, no extra Railway service, no extra cost. The
  tradeoff is the scheduler only runs while the web dyno is up — if
  Railway restarts/redeploys your service around 03:00, that day's job
  can be skipped, and if the free/hobby plan sleeps or recycles the
  container, timing isn't guaranteed.
- **Separate Railway worker service:** more robust — a dedicated
  always-on process just for the cron job means it's decoupled from web
  traffic/restarts and far more likely to fire reliably every day. This
  costs more (a second service billed separately) and adds deployment
  complexity (two Dockerfiles/services to manage, shared DB access to
  coordinate).

**Recommendation for a non-expert getting started: keep the same-process
setup.** It's zero extra cost/complexity, and an occasional missed 3am
scrape (rare, and only around a redeploy) is a minor inconvenience, not a
correctness problem — you can always trigger `POST /api/scrape/all`
manually to catch up. Revisit a separate worker service only if daily
scrapes become business-critical.

## Legal / scraping etiquette

This is for personal investment research only, not a commercial data
product. When/if live scraping is implemented against county sites:
- Respect each site's `robots.txt`.
- Rate-limit requests (the `BaseScraper` class enforces a minimum delay
  and capped retries with backoff) — do not hammer county infrastructure.
- Prefer an official data feed or API over scraping if one is offered by
  the county or RealAuction.
- Re-check each county's terms of use; some clerk sites explicitly restrict
  automated access.

## Known limitations

- The RealAuction Playwright scraper (`realauction_playwright.py`) is
  written and unit-tested against real captured page structure, but has not
  yet been run end-to-end against the live internet — see "Scrapers"
  section above for why (sandbox has no Chromium OS deps and no network
  route to realforeclose.com). Needs a live smoke test once deployed.
- Lake and Osceola do not run mortgage foreclosure sales through RealAuction
  (confirmed live - their `realforeclose.com` calendars are offline); only
  their tax deed sales are covered via `realtaxdeed.com`.
- `absorption_rate` has no integrated free data source — permanently a
  placeholder until one is found/subscribed to.
- `flood_zone` FEMA lookup is not fully wired to a live per-address query in
  this build; treat as "verify manually" unless you see a real value.
- `crime_rate` requires a free `api.data.gov` key to be populated; otherwise
  shows "unavailable."
- Demo/sample properties exist only to prove the API/UI works; they are
  fictional and clearly labeled everywhere (`is_demo_data`, notes prefix,
  `raw_scraped_json` tag) — never mistake them for real auction listings.
- Title search is a stub with no default provider — you must supply your
  own key/provider and implement the actual call in
  `title_search_provider()`.
