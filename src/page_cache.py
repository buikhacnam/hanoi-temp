"""Twelve-hour edge page caching, with windows defined in Hanoi local time."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from weather import HANOI_TZ

# Bump this when changing rendered markup so deployments do not reuse old pages.
CACHE_VERSION = 'v3'
INTERVAL_HOURS = 12


def cache_window(url, metric, now=None, *, sort='year', order='desc'):
    local = (now or datetime.now(timezone.utc)).astimezone(HANOI_TZ)
    start = local.replace(hour=(local.hour // INTERVAL_HOURS)*INTERVAL_HOURS,
                          minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=INTERVAL_HOURS)
    origin = urlsplit(url)
    key = f'{origin.scheme}://{origin.netloc}/__page_cache/{CACHE_VERSION}/{local.date()}/{start.hour:02d}/{metric}/{sort}/{order}'
    return key, start, end


def cache_ttl(end, now=None):
    return max(0, min(INTERVAL_HOURS*3600, int((end-(now or datetime.now(timezone.utc))).total_seconds())))


async def cached_page(key):
    try:
        from js import caches, Response as JSResponse
        cached = await caches.default.match(key)
        if cached is None:
            return None
        response = JSResponse.new(cached.body, cached)
        response.headers.set('X-Page-Cache', 'HIT')
        return response
    except ImportError:
        return None  # CPython unit tests have no Workers runtime.
    except Exception as exc:
        print(f'Page cache lookup failed; rendering from D1: {exc}')
        return None


async def store_page(key, response):
    try:
        from js import caches
        await caches.default.put(key, response.js_object.clone())
    except ImportError:
        return
    except Exception as exc:
        # Cache failures must never hide a valid page.
        print(f'Page cache write failed: {exc}')
