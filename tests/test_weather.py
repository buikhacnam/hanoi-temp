from copy import deepcopy
from datetime import date, datetime, timezone
import sqlite3
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from weather import UPSERT, api_url, parse_daily, today_hanoi

class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.day=date(2024,2,29)
        self.payload={'daily_units': {v:'°C' for v in ['temperature_2m_mean','temperature_2m_max','temperature_2m_min']},'daily':{'time':['2024-02-29'],'temperature_2m_mean':[23.5],'temperature_2m_max':[27.1],'temperature_2m_min':[19.2]}}
    def test_hanoi_midnight(self):
        self.assertEqual(today_hanoi(datetime(2026,11,6,16,59,tzinfo=timezone.utc)),date(2026,11,6))
        self.assertEqual(today_hanoi(datetime(2026,11,6,17,0,tzinfo=timezone.utc)),date(2026,11,7))
    def test_explicit_consistent_model_and_timezone(self):
        url=api_url('historical',self.day,self.day)
        self.assertIn('models=era5',url)
        self.assertIn('Asia%2FHo_Chi_Minh',url)
    def test_missing_day_rejected(self):
        self.payload['daily']['time']=[]
        with self.assertRaises(ValueError): parse_daily(self.payload,'historical',self.day,self.day)
    def test_wrong_units_rejected(self):
        self.payload['daily_units']['temperature_2m_mean']='°F'
        with self.assertRaises(ValueError): parse_daily(self.payload,'historical',self.day,self.day)
    def test_invalid_temperatures_rejected(self):
        for value in [None,float('nan'),float('inf'),True,100,'23.5']:
            with self.subTest(value=value):
                payload=deepcopy(self.payload);payload['daily']['temperature_2m_mean']=[value]
                with self.assertRaises(ValueError): parse_daily(payload,'historical',self.day,self.day)
    def test_seed_can_preserve_upstream_gap(self):
        self.payload['daily']['temperature_2m_mean']=[None]
        self.assertEqual(parse_daily(self.payload,'historical',self.day,self.day,allow_missing=True),[])
    def test_inverted_range_rejected(self):
        self.payload['daily']['temperature_2m_min']=[30]
        with self.assertRaises(ValueError): parse_daily(self.payload,'historical',self.day,self.day)
    def test_upsert_keeps_history_separate_and_calendar_query_indexed(self):
        db=sqlite3.connect(':memory:');db.executescript((ROOT/'migrations/0001_weather.sql').read_text())
        for kind in ['historical','forecast','historical']:
            db.execute(UPSERT,parse_daily(self.payload,kind,self.day,self.day)[0])
        self.assertEqual(db.execute('SELECT count(*) FROM weather_daily').fetchone()[0],2)
        db.execute(UPSERT,('2023-02-28','historical','02-28',22,25,19,'era5','2026-11-07T00:00:00+00:00'))
        rows=db.execute("SELECT date FROM weather_daily WHERE kind='historical' AND month_day='02-29' AND date<'2026-02-28'").fetchall()
        self.assertEqual(rows,[('2024-02-29',)])
        plan=db.execute("EXPLAIN QUERY PLAN SELECT * FROM weather_daily WHERE kind='historical' AND month_day='02-29' ORDER BY date").fetchall()
        self.assertIn('weather_calendar_day',str(plan))

if __name__=='__main__': unittest.main()
