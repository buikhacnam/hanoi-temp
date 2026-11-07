"""API behavior tests; the deployed Python/D1 adapter is also exercised locally."""
import importlib
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import unittest

# The SDK imports browser/Wasm modules unavailable in CPython.
class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}

    @staticmethod
    def json(body, status=200, headers=None):
        return SimpleNamespace(body=body,status=status,headers=headers or {})

with patch.dict(sys.modules, {'js':SimpleNamespace(AbortSignal=None),
        'workers':SimpleNamespace(Response=Response,WorkerEntrypoint=object,fetch=None)}):
    entry=importlib.import_module('entry')

class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_current_forecast_is_requested(self):
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        request=SimpleNamespace(url='https://weather.example/api/today',method='GET')
        with patch.object(entry,'today_hanoi',return_value=date(2026,11,7)),patch.object(entry,'query',new=AsyncMock(side_effect=[[],[]])) as query:
            response=await app.fetch(request)
        self.assertEqual(response.status,200)
        self.assertEqual(response.body['date'],'2026-11-07')
        self.assertIsNone(response.body['today'])
        self.assertEqual(query.await_args_list[1].args[-1],'2026-11-07')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
    async def test_html_contains_data_without_browser_javascript(self):
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        request=SimpleNamespace(url='https://weather.example/?metric=high',method='GET')
        with patch.object(entry,'today_hanoi',return_value=date(2026,11,7)),patch.object(entry,'query',new=AsyncMock(side_effect=[[],[]])):
            response=await app.fetch(request)
        self.assertEqual(response.status,200)
        self.assertIn('Daily high temperature',response.body)
        self.assertIn('aria-current="page">High</a>',response.body)
        self.assertNotIn('<script',response.body)
        self.assertIn("script-src 'none'",response.headers['Content-Security-Policy'])

    async def test_cache_hit_skips_database_and_rendering(self):
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        request=SimpleNamespace(url='https://weather.example/?metric=high&tracking=a',method='GET')
        cached=object()
        with patch.object(entry,'cached_page',new=AsyncMock(return_value=cached)),patch.object(entry,'query',new=AsyncMock()) as query,patch.object(entry,'render_page') as render:
            self.assertIs(await app.fetch(request),cached)
        query.assert_not_awaited()
        render.assert_not_called()

    async def test_current_forecast_is_cached_but_previous_window_is_not(self):
        now=datetime.now(timezone.utc)
        key,start,end=entry.cache_window('https://weather.example/','mean',now)
        forecast=dict(date=str(start.date()),kind='forecast',mean=25.,high=28.,low=22.,updated_at=now.isoformat())
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        request=SimpleNamespace(url='https://weather.example/',method='GET')
        for fresh in [True,False]:
            forecast['updated_at']=(now if fresh else start-timedelta(minutes=1)).isoformat()
            with patch.object(entry,'cached_page',new=AsyncMock(return_value=None)),patch.object(entry,'store_page',new=AsyncMock()) as store,patch.object(entry,'today_hanoi',return_value=start.date()),patch.object(entry,'query',new=AsyncMock(side_effect=[[],[forecast]])):
                response=await app.fetch(request)
            self.assertEqual(response.headers['X-Page-Cache'],'MISS' if fresh else 'BYPASS')
            self.assertEqual(store.await_count,1 if fresh else 0)

    async def test_head_and_api_bypass_cache(self):
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        for path,method in [('/','HEAD'),('/api/today','GET')]:
            request=SimpleNamespace(url='https://weather.example'+path,method=method)
            with patch.object(entry,'cached_page',new=AsyncMock()) as lookup,patch.object(entry,'store_page',new=AsyncMock()) as store,patch.object(entry,'query',new=AsyncMock(side_effect=[[],[]])):
                await app.fetch(request)
            lookup.assert_not_awaited()
            store.assert_not_awaited()

    async def test_html_errors_are_not_cached(self):
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        request=SimpleNamespace(url='https://weather.example/',method='GET')
        with patch.object(entry,'cached_page',new=AsyncMock(return_value=None)),patch.object(entry,'store_page',new=AsyncMock()) as store,patch.object(entry,'query',new=AsyncMock(side_effect=RuntimeError('offline'))),patch.object(entry.traceback,'print_exc'):
            response=await app.fetch(request)
        self.assertEqual(response.status,503)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        store.assert_not_awaited()

    async def test_database_failure_returns_retryable_response(self):
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        request=SimpleNamespace(url='https://weather.example/api/today',method='GET')
        with patch.object(entry,'query',new=AsyncMock(side_effect=RuntimeError('database offline'))),patch.object(entry.traceback,'print_exc'):
            response=await app.fetch(request)
        self.assertEqual(response.status,503)
        self.assertNotIn('database offline',response.body['error'])
    async def test_forecast_failure_does_not_skip_historical_reconciliation(self):
        ingest=AsyncMock(side_effect=[RuntimeError('forecast offline'),None])
        db=SimpleNamespace(prepare=lambda sql:SimpleNamespace(bind=lambda *args:SimpleNamespace(run=AsyncMock())))
        with patch.object(entry,'today_hanoi',return_value=date(2026,11,7)),patch.object(entry,'query',new=AsyncMock(return_value=[{'latest':'2026-10-30'}])),patch.object(entry,'ingest',new=ingest):
            with self.assertRaisesRegex(RuntimeError,'forecast offline'):
                await entry.update_weather(db)
        self.assertEqual(ingest.await_count,2)
        self.assertEqual(ingest.await_args_list[1].args[1:],('historical',date(2026,10,16),date(2026,10,31)))
    async def test_long_outage_has_bounded_catchup_window(self):
        ingest=AsyncMock()
        db=SimpleNamespace(prepare=lambda sql:SimpleNamespace(bind=lambda *args:SimpleNamespace(run=AsyncMock())))
        with patch.object(entry,'today_hanoi',return_value=date(2026,11,7)),patch.object(entry,'query',new=AsyncMock(return_value=[{'latest':'2026-01-01'}])),patch.object(entry,'ingest',new=ingest):
            await entry.update_weather(db)
        _,_,start,end=ingest.await_args_list[1].args
        self.assertEqual((end-start).days,30)
        self.assertEqual(start,date(2025,12,18))

    async def test_sort_query_is_normalized_before_cache_lookup(self):
        app=entry.Default();app.env=SimpleNamespace(DB=object())
        for query,sort,order in [('sort=low&order=asc','low','asc'),
                                 ('sort=invalid&order=invalid','year','desc')]:
            request=SimpleNamespace(url='https://weather.example/?'+query,method='GET')
            with patch.object(entry,'cached_page',new=AsyncMock(return_value=object())) as lookup:
                await app.fetch(request)
            self.assertTrue(lookup.await_args.args[0].endswith(f'/mean/{sort}/{order}'))
