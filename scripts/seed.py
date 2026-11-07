#!/usr/bin/env python3
"""Resumable ERA5 download + D1 import. No public write/admin endpoint."""
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from weather import api_url, parse_daily, today_hanoi


def download(url):
    for attempt in range(5):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'hanoi-temp/1.0'}), timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            time.sleep(max(10 * (attempt+1), min(120, int(exc.headers.get('Retry-After', '0')))))
        except (URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(5*(attempt+1))


def sql_value(value):
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + value.replace("'", "''") + "'"


def write_sql(records, path):
    columns = 'date,kind,month_day,mean,high,low,model,updated_at'
    suffix = (' ON CONFLICT(date,kind) DO UPDATE SET mean=excluded.mean,high=excluded.high,'
              'low=excluded.low,model=excluded.model,updated_at=excluded.updated_at;\n')
    path.write_text(''.join('INSERT INTO weather_daily ('+columns+') VALUES ('+
        ','.join(map(sql_value, record))+')'+suffix for record in records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year', type=int, default=1940)
    parser.add_argument('--end-year', type=int, default=(today_hanoi()-timedelta(days=7)).year)
    parser.add_argument('--remote', action='store_true', help='Import to configured production D1 instead of local D1')
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='Redownload cached years')
    args = parser.parse_args()
    cutoff = today_hanoi()-timedelta(days=7)
    if not 1940 <= args.start_year <= args.end_year <= cutoff.year:
        parser.error('Year range must be between 1940 and the latest available year')
    cache = ROOT/'data'/'seed'
    cache.mkdir(parents=True, exist_ok=True)
    for year in range(args.start_year, args.end_year+1):
        start, end = date(year, 1, 1), min(date(year, 12, 31), cutoff)
        path = cache/f'{year}-{end.isoformat()}-era5.json'
        if path.exists() and not args.refresh:
            payload = json.loads(path.read_text())
        else:
            print(f'Downloading ERA5 {start} through {end}', flush=True)
            payload = download(api_url('historical', start, end))
            parse_daily(payload, 'historical', start, end, allow_missing=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(payload))
            temp.replace(path)
            # Long date ranges count as multiple upstream API calls.
            time.sleep(4)
        records = parse_daily(payload, 'historical', start, end, allow_missing=True)
        expected = (end-start).days+1
        if not records:
            raise ValueError(f'No valid temperatures for {year}')
        if len(records) < expected:
            print(f'{year}: {expected-len(records)} dates unavailable upstream; leaving gaps rather than inventing values.', flush=True)
        sql = cache/f'{year}.sql'
        write_sql(records, sql)
        if not args.download_only:
            command = [str(ROOT/'node_modules/.bin/wrangler'), 'd1', 'execute', 'DB',
                       '--remote' if args.remote else '--local', '--file', str(sql), '--yes']
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, env={**os.environ,
                'WRANGLER_LOG_PATH': str(ROOT/'.wrangler/logs'), 'WRANGLER_SEND_METRICS':'false'})
        print(f'{year}: {len(records)} rows '+('prepared' if args.download_only else 'imported'), flush=True)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(exc.stdout, file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        raise SystemExit(exc.returncode)
