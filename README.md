# Hanoi Temp

Today's temperature in Hanoi compared with the same calendar day since 1940.
Python Cloudflare Worker + D1. Celsius only.

## Local setup

Requires Node.js, Python 3.12+, and uv. The development dependencies include
**uv 0.13.4+**, required by current pywrangler; `uv sync` installs it inside the
project environment without changing your global uv installation.

```sh
npm ci
uv sync
npm run db:migrate
npm run seed
npm run dev
```

Open http://localhost:8787. Seed defaults to local D1 and downloads every daily
mean/high/low from 1940 through seven days ago. It takes several minutes. Downloads
are validated, cached under ignored `data/seed/`, and paced to respect upstream
rate limits. Rerunning reuses downloads and upserts records without duplicates.
No web-accessible endpoint can write or seed the database.

```sh
# Optional limited import, or prepare downloads without touching D1:
npm run seed -- --start-year 1991 --end-year 2020
npm run seed -- --download-only
# Redownload cached years when reconciling upstream revisions:
npm run seed -- --start-year 2020 --end-year 2020 --refresh
```

Sample query:

```sh
npx wrangler d1 execute DB --local --command \
  "SELECT date, mean, high, low, kind FROM weather_daily WHERE month_day='11-07' ORDER BY date DESC"
```

Cron does not run automatically in local development. With the dev server running,
trigger the initial forecast/reconciliation once:

```sh
curl http://localhost:8787/cdn-cgi/local/scheduled
```

Local Explorer (URL printed by Wrangler) can inspect bindings, D1 rows, and logs.
The read API is `GET /api/today`; it returns only today's calendar day in Hanoi.
An empty or incomplete import is shown explicitly; the app never invents values.

## Data and updates

- Hanoi coordinates: 21.0285, 105.8542. All days use `Asia/Ho_Chi_Minh` (UTC+7).
- Historical: Open-Meteo Historical Weather API, explicitly `models=era5`.
- Today: Open-Meteo Forecast API, best-match model; full-day forecast, not an
  instantaneous temperature or a finalized observation.
- Separate `(date, kind)` keys prevent forecasts from overwriting ERA5 history.
- Cron runs every twelve hours, at midnight and noon Hanoi. It updates today's
  forecast and re-fetches a historical overlap ending seven days ago. If several
  runs were missed, it catches up from the latest stored historical date in
  bounded windows. Seed the full history before relying on cron for maintenance.
- On upstream failure, valid stored rows remain. Forecasts older than twelve hours
  are labeled, and yesterday's forecast is never used as today's forecast.
- Null upstream values are omitted during seeding and reported as gaps. For
  example, 1940-01-01 lacks a daily mean at this timezone boundary. Re-run a year
  with `--refresh` to check for upstream corrections. Missing values are not zero.
- Baseline: the same date during 1991–2020, only when all expected years exist
  (30 normally, 8 for February 29). Historical extrema exclude today's forecast.
- The Worker renders complete HTML and SVG directly from D1. CSS is inline in the page template; there is no public assets directory or
  static-assets binding. No browser JavaScript is shipped. Mean/high/low controls are ordinary links (`?metric=mean`, `high`, or
  `low`). The date is calculated in Hanoi on each request. HTML pages use a twelve-hour
  Cloudflare Cache API cache, split by Hanoi date, midnight/noon window, and metric.
  Browser caching is disabled (`max-age=0`); edge expiry stops at the next window
  boundary. Cache hits skip D1 and HTML rendering. API responses, errors, missing
  forecasts, and forecasts from the preceding window are not cached. Cache
  operations are local to each Cloudflare data center; eviction can occur early.
  `X-Page-Cache` reports `HIT`, `MISS`, or `BYPASS`. Bump `CACHE_VERSION` in
  `src/page_cache.py` when changing page markup or rendering. The methodology section and chart titles use native HTML/SVG.

## Production

Live app: https://hanoi-temp.buinam.workers.dev

- Worker: `hanoi-temp`
- D1 database: `hanoi-temp` (binding `DB`)
- Production database ID: `08aa32e3-034c-48cc-8e3b-2de538591d0a`
- Historical records and today's forecast have been imported into production.
- Cron updates run at 00:00 and 12:00 Hanoi time.

The production binding is configured in `wrangler.jsonc`. Its separate
`preview_database_id` preserves the existing local database. Keep the conventional
`README.md` and `wrangler.jsonc` filenames so project tools discover them normally.

For subsequent code or schema changes:

```sh
npm test
npm run types
npm run db:migrate:remote
npm run deploy
```

To refresh/reseed production explicitly:

```sh
npm run seed -- --remote
```

Remote operations require a Cloudflare account with Workers/D1 permissions.
The remote seed uses cached responses and upserts records without duplicates.
To set up a separate account, use `npx wrangler login`, create a new database with
`npx wrangler d1 create hanoi-temp`, update `database_id`, apply migrations, seed,
and deploy. No secrets are needed for Open-Meteo's non-commercial free endpoints.
Commercial use requires reviewing their plan and terms.

## Validation

```sh
npm test
npm run types
```

Tests cover Hanoi midnight, explicit model/timezone selection, invalid and missing
upstream values, leap dates, idempotent upserts, forecast/history isolation, and
indexed calendar-day queries. The local Worker should also be checked through
`/api/today` and the scheduled endpoint after applying migrations.

## Sources

Weather: [Open-Meteo](https://open-meteo.com/), [Historical API](https://open-meteo.com/en/docs/historical-weather-api),
[Forecast API](https://open-meteo.com/en/docs), [Terms](https://open-meteo.com/en/terms).
Data attribution: CC BY 4.0; ERA5 / Copernicus Climate Change Service (C3S), ECMWF.

Cloudflare: [Python Workers](https://developers.cloudflare.com/workers/languages/python/),
[D1](https://developers.cloudflare.com/d1/),
[Cron](https://developers.cloudflare.com/workers/configuration/cron-triggers/).
