from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rendering import render_page


def row(year,day='11-07',**kwargs):
    return dict(date=f'{year}-{day}',kind='historical',mean=20.,high=24.,low=16.,**kwargs)


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.history=[row(y) for y in range(1940,2026)]
        self.current={**row(2026),'kind':'forecast','mean':25.,'high':29.,'low':21.,'updated_at':'2026-11-07T00:00:00+00:00'}
        self.data=dict(date='2026-11-07',history=self.history,today=self.current)

    def test_complete_page_has_history_chart_and_correct_baseline(self):
        page=render_page(self.data)
        self.assertIn('5.0°C warmer',page)
        self.assertIn('20.0°C · 1991–2020 average',page)
        self.assertEqual(page.count('<tr class='),87)
        self.assertIn('1940</th>',page)
        self.assertIn('2026 · Today</th>',page)
        self.assertIn('<title>2026 · 25.0°C · forecast</title>',page)
        self.assertNotIn('{{',page)
        self.assertNotIn('<script',page)
        self.assertNotIn('app.js',page)

    def test_each_metric_is_rendered_and_invalid_query_cannot_inject_html(self):
        for metric,value in [('mean','25.0'),('high','29.0'),('low','21.0')]:
            page=render_page(self.data,metric)
            self.assertIn(f'id="temperature">{value}</span>',page)
            self.assertIn(f'href="/?metric={metric}" aria-current="page"',page)
        page=render_page(self.data,'<script>alert(1)</script>')
        self.assertIn('id="temperature">25.0</span>',page)
        self.assertNotIn('<script',page)

    def test_missing_baseline_is_not_reported_as_a_complete_average(self):
        self.data['history']=[r for r in self.history if r['date']!='2000-11-07']
        page=render_page(self.data)
        self.assertIn('Comparison unavailable',page)
        self.assertIn('1991–2020 baseline unavailable',page)
        self.assertIn('Historical import incomplete',page)

    def test_leap_day_uses_only_eight_baseline_years(self):
        self.data['date']='2024-02-29'
        self.data['history']=[row(y,'02-29') for y in range(1940,2024,4)]
        self.data['today']={**self.current,'date':'2024-02-29'}
        page=render_page(self.data)
        self.assertIn('20.0°C · 1991–2020 average',page)
        self.assertNotIn('Historical import incomplete',page)

    def test_empty_database_and_server_error_render_useful_html(self):
        page=render_page(dict(date='2026-11-07',history=[],today=None),error=True)
        self.assertIn('Weather data is temporarily unavailable',page)
        self.assertIn('Today · November 7, 2026',page)
        self.assertIn('Weather history is not available yet.',page)
        self.assertNotIn('nan',page.lower())
        self.assertNotIn('{{',page)
