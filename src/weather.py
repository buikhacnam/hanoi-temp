"""Shared weather validation and storage contract (also used by the seed CLI)."""
from datetime import date, datetime, timedelta, timezone
import math
from urllib.parse import urlencode

HANOI_TZ = timezone(timedelta(hours=7))
VARIABLES = ('temperature_2m_mean', 'temperature_2m_max', 'temperature_2m_min')
UPSERT = """INSERT INTO weather_daily
(date,kind,month_day,mean,high,low,model,updated_at) VALUES (?,?,?,?,?,?,?,?)
ON CONFLICT(date,kind) DO UPDATE SET mean=excluded.mean,high=excluded.high,
low=excluded.low,model=excluded.model,updated_at=excluded.updated_at"""


def today_hanoi(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(HANOI_TZ).date()


def api_url(kind, start, end):
    params = dict(latitude='21.0285', longitude='105.8542',
                  timezone='Asia/Ho_Chi_Minh', temperature_unit='celsius',
                  daily=','.join(VARIABLES), start_date=str(start), end_date=str(end))
    if kind == 'historical':
        params['models'] = 'era5'
        endpoint = 'https://archive-api.open-meteo.com/v1/archive'
    else:
        endpoint = 'https://api.open-meteo.com/v1/forecast'
    return endpoint + '?' + urlencode(params)


def parse_daily(payload, kind, start, end, *, allow_missing=False):
    """Reject incomplete/invalid responses before writing any records."""
    if kind not in ('historical', 'forecast'):
        raise ValueError('Unknown weather kind')
    daily = payload.get('daily', {})
    dates = daily.get('time', [])
    expected = [(start + timedelta(days=i)).isoformat()
                for i in range((end-start).days+1)]
    if dates != expected:
        raise ValueError('Weather response does not cover the requested dates')
    columns = [daily.get(v, []) for v in VARIABLES]
    if any(len(c) != len(dates) for c in columns):
        raise ValueError('Weather response has incomplete temperature arrays')
    units = payload.get('daily_units', {})
    if any(units.get(v) != '°C' for v in VARIABLES):
        raise ValueError('Weather response must use Celsius')
    stamp = datetime.now(timezone.utc).isoformat()
    records = []
    for i, day in enumerate(dates):
        values = [c[i] for c in columns]
        if allow_missing and any(v is None for v in values):
            continue
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or not -90 <= v <= 65 for v in values):
            raise ValueError(f'Missing or invalid temperatures for {day}')
        mean, high, low = values
        if not low <= mean <= high:
            raise ValueError(f'Inconsistent temperature range for {day}')
        records.append((day, kind, day[5:], mean, high, low,
                        'era5' if kind == 'historical' else 'best_match', stamp))
    return records
