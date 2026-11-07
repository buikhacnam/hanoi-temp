import traceback
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from js import AbortSignal
from workers import Response, WorkerEntrypoint, fetch
from weather import UPSERT, api_url, parse_daily, today_hanoi
from rendering import render_page, normalize_sort
from page_cache import cached_page, store_page, cache_window, cache_ttl, INTERVAL_HOURS


async def query(db, sql, *params):
    result = await db.prepare(sql).bind(*params).all()
    return result.results


async def ingest(db, kind, start, end):
    response = await fetch(api_url(kind, start, end), signal=AbortSignal.timeout(30000))
    if not response.ok:
        raise RuntimeError(f'{kind} weather service returned {response.status}')
    records = parse_daily(await response.json(), kind, start, end)
    # Small batches bound CPU use and isolate storage failures.
    for i in range(0, len(records), 50):
        await db.batch([db.prepare(UPSERT).bind(*r) for r in records[i:i+50]])
    print(f'Updated {len(records)} {kind} weather records')


async def update_weather(db):
    today = today_hanoi()
    errors = []
    # Keep forecast/history independent so one upstream failure cannot block both.
    try:
        await ingest(db, 'forecast', today, today)
    except Exception as exc:
        errors.append(str(exc))
    try:
        rows = await query(db, "SELECT MAX(date) AS latest FROM weather_daily WHERE kind='historical'")
        latest = rows[0]['latest']
        start = date.fromisoformat(latest)-timedelta(days=14) if latest else today-timedelta(days=21)
        start = max(date(1940, 1, 1), start)
        end = min(today-timedelta(days=7), start+timedelta(days=30))
        if start <= end:
            await ingest(db, 'historical', start, end)
        # Delete expired forecasts only; ERA5 history is never removed.
        await db.prepare("DELETE FROM weather_daily WHERE kind='forecast' AND date < ?").bind(
            str(today-timedelta(days=14))).run()
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        raise RuntimeError('; '.join(errors))


def html_response(page, status=200, *, ttl=0, cache_status="BYPASS"):
    return Response(page, status=status, headers={
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': f'public, max-age=0, s-maxage={ttl}, must-revalidate' if ttl else 'no-store',
        'X-Page-Cache': cache_status,
        'Content-Security-Policy': "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    })


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlsplit(request.url)
        path = url.path
        is_page = path in ('/', '/index.html')
        if not is_page and path != '/api/today':
            return Response.json({'error': 'Not found'}, status=404)
        if request.method not in ('GET', 'HEAD'):
            return Response.json({'error': 'Method not allowed'}, status=405,
                                 headers={'Allow': 'GET, HEAD'})
        metric = parse_qs(url.query).get('metric', ['mean'])[0]
        metric = metric if metric in ('mean', 'high', 'low') else 'mean'
        params = parse_qs(url.query)
        sort, order = normalize_sort(params.get('sort', ['year'])[0], params.get('order', ['desc'])[0])
        key, window_start, window_end = cache_window(request.url, metric, sort=sort, order=order)
        if is_page and request.method == 'GET':
            cached = await cached_page(key)
            if cached is not None:
                return cached
        try:
            today = today_hanoi()
            history = await query(self.env.DB,
                "SELECT * FROM weather_daily WHERE kind='historical' AND month_day=? AND date<? ORDER BY date",
                today.strftime('%m-%d'), str(today))
            forecast = await query(self.env.DB,
                "SELECT * FROM weather_daily WHERE kind='forecast' AND date=?", str(today))
            # Never substitute yesterday's forecast for today's data.
            current = forecast[0] if forecast else None
            stale = bool(current and (datetime.now(timezone.utc) -
                datetime.fromisoformat(current['updated_at'])).total_seconds() > INTERVAL_HOURS*3600)
            data = dict(date=str(today), timezone='Asia/Ho_Chi_Minh',
                location='Hanoi, Vietnam', history=history, today=current,
                forecast_stale=stale, baseline_start=1991, baseline_end=2020)
            if is_page:
                # A request can arrive just before cron finishes at noon/midnight.
                # Do not retain the preceding window's forecast for another 12 hours.
                current_key, _, _ = cache_window(request.url, metric, sort=sort, order=order)
                eligible = (request.method == 'GET' and current and not stale
                    and datetime.fromisoformat(current['updated_at']) >= window_start
                    and str(today) == str(window_start.date()) and current_key == key)
                ttl = cache_ttl(window_end) if eligible else 0
                response = html_response(render_page(data, metric, sort=sort, order=order), ttl=ttl,
                    cache_status='MISS' if ttl else 'BYPASS')
                if ttl:
                    await store_page(key, response)
                return response
            return Response.json(data, headers={'Cache-Control': 'no-store'})
        except Exception:
            traceback.print_exc()
            if is_page:
                data = dict(date=str(today_hanoi()), history=[], today=None)
                return html_response(render_page(data, metric, sort=sort, order=order, error=True), status=503)
            return Response.json({'error': 'Weather data is temporarily unavailable. Please try again.'},
                                 status=503, headers={'Cache-Control': 'no-store'})

    async def scheduled(self, controller, env, ctx):
        await update_weather(self.env.DB)
