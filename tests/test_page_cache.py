from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from page_cache import cache_window, cache_ttl

class CacheWindowTests(unittest.TestCase):
    def test_noon_switches_key_and_expires_previous_window(self):
        before=datetime(2026,11,7,4,59,59,tzinfo=timezone.utc)
        after=datetime(2026,11,7,5,0,0,tzinfo=timezone.utc)
        key,_,end=cache_window('https://weather.example/','mean',before)
        new_key,start,new_end=cache_window('https://weather.example/','mean',after)
        self.assertNotEqual(key,new_key)
        self.assertEqual(cache_ttl(end,before),1)
        self.assertEqual(cache_ttl(end,after),0)
        self.assertEqual(cache_ttl(new_end,after),43200)
        self.assertEqual(start.hour,12)
    def test_midnight_uses_new_hanoi_date(self):
        before=datetime(2026,11,7,16,59,59,tzinfo=timezone.utc)
        after=datetime(2026,11,7,17,0,0,tzinfo=timezone.utc)
        key,_,end=cache_window('https://weather.example/','mean',before)
        new_key,start,_=cache_window('https://weather.example/','mean',after)
        self.assertIn('/2026-11-07/12/mean',key)
        self.assertIn('/2026-11-08/00/mean',new_key)
        self.assertEqual(cache_ttl(end,after),0)
    def test_only_metric_changes_entry_not_alias_or_tracking_query(self):
        now=datetime(2026,11,7,6,tzinfo=timezone.utc)
        key=cache_window('https://weather.example/','mean',now)[0]
        self.assertEqual(key,cache_window('https://weather.example/index.html?tracking=abc','mean',now)[0])
        self.assertNotEqual(key,cache_window('https://weather.example/','high',now)[0])

    def test_sort_variants_have_separate_cache_entries(self):
        now=datetime(2026,11,7,6,tzinfo=timezone.utc)
        keys={cache_window('https://weather.example/','mean',now,sort=sort,order=order)[0]
              for sort in ('year','mean','high','low') for order in ('asc','desc')}
        self.assertEqual(len(keys),8)
