"""HTML and SVG rendering. The delivered page needs no browser JavaScript."""
import calendar
from datetime import date, datetime
from html import escape
import math
import re
from urllib.parse import urlencode

from page_template import PAGE
from weather import HANOI_TZ

METRICS = {'mean': 'Daily mean', 'high': 'Daily high', 'low': 'Daily low'}

SORT_COLUMNS = {'year': 'Year', 'mean': 'Average', 'high': 'High', 'low': 'Low'}


def normalize_sort(sort, order):
    return (sort if sort in SORT_COLUMNS else 'year',
            order if order in ('asc', 'desc') else 'desc')


def fmt(value):
    return f'{value:.1f}' if isinstance(value, (int, float)) and math.isfinite(value) else '—'


def year_of(row):
    return int(row['date'][:4])


def chart_svg(history, current, baseline, year, metric, leap):
    rows = history + ([current] if current else [])
    if not rows:
        return '<text x="550" y="130" text-anchor="middle" fill="#78817a">Weather history is not available yet.</text>'
    values = [r[metric] for r in rows]
    low = math.floor((min(values)-1)/2)*2
    high = math.ceil((max(values)+1)/2)*2
    def x(y):
        return 42+(y-1940)/max(1,year-1940)*1013
    def y(t):
        return 222-(t-low)/(high-low)*203
    out = []
    for t in range(low,high+1,2):
        out.append(f'<line x1="42" y1="{y(t):.2f}" x2="1055" y2="{y(t):.2f}" stroke="#efefe9"/><text x="30" y="{y(t)+4:.2f}" text-anchor="end" fill="#78817a" font-size="11">{t}°</text>')
    for tick in [1940]+list(range(1960,year-5,20))+[year]:
        out.append(f'<text x="{x(tick):.2f}" y="251" text-anchor="middle" fill="#78817a" font-size="11">{tick}</text>')
    if baseline is not None:
        out.append(f'<line x1="42" y1="{y(baseline):.2f}" x2="1055" y2="{y(baseline):.2f}" stroke="#a5a68c" stroke-dasharray="5 5"/>')
    path = ' '.join(f'{"L" if i and year_of(row)-year_of(history[i-1]) == (4 if leap else 1) else "M"}{x(year_of(row)):.2f},{y(row[metric]):.2f}' for i,row in enumerate(history))
    out.append(f'<path d="{path}" fill="none" stroke="#9ca68d" stroke-width="1.6" stroke-opacity=".75"/>')
    for row in rows:
        forecast = row['kind']=='forecast'
        title = f'{year_of(row)} · {fmt(row[metric])}°C · {"forecast" if forecast else "ERA5 estimate"}'
        out.append(f'<circle class="chart-point" cx="{x(year_of(row)):.2f}" cy="{y(row[metric]):.2f}" r="{6 if forecast else 3}" fill="{"#d86435" if forecast else "#929f83"}" stroke="white" stroke-width="{3 if forecast else 1}"><title>{escape(title)}</title></circle>')
    return ''.join(out)


def render_page(data, metric='mean', *, sort='year', order='desc', error=False):
    sort, order = normalize_sort(sort, order)
    metric = metric if metric in METRICS else 'mean'
    today = date.fromisoformat(data['date'])
    date_text = f'{today:%B} {today.day}'
    history, current = data['history'], data['today']
    leap = today.month==2 and today.day==29
    expected_years = {y for y in range(1940,today.year) if not leap or calendar.isleap(y)}
    baseline_years = {y for y in range(1991,2021) if not leap or calendar.isleap(y)}
    base_rows = [r for r in history if year_of(r) in baseline_years]
    baseline = sum(r[metric] for r in base_rows)/len(base_rows) if {year_of(r) for r in base_rows}==baseline_years else None
    delta = current[metric]-baseline if current and baseline is not None else None
    notices = []
    if error:
        notices.append('Weather data is temporarily unavailable. Please reload to try again.')
    elif expected_years-{year_of(r) for r in history}:
        notices.append(f'Historical import incomplete: {len(history)} of {len(expected_years)} years available for this day.')
    if not error and not current:
        notices.append('Today’s forecast is unavailable. Historical data remains available.')
    if data.get('forecast_stale'):
        notices.append('The forecast is older than 12 hours.')
    if current:
        stamp = datetime.fromisoformat(current['updated_at']).astimezone(HANOI_TZ)
        notices.append(f'Forecast updated {stamp:%b} {stamp.day}, {stamp:%H:%M} · Hanoi time')
    notices.append('Forecast updates at 00:00 and 12:00 Hanoi time.')
    values = {
        'data_status': ' '.join(notices),
        'status_class': 'data-warning' if error or not current or data.get('forecast_stale') or len(history)<len(expected_years) else '',
        'day_title': f'Today · {date_text}, {today.year}',
        'temperature': fmt(current[metric] if current else None),
        'metric_label': f'{METRICS[metric]} temperature · {"full-day forecast" if current else "forecast unavailable"}',
        'forecast_badge': 'OLDER FORECAST' if data.get('forecast_stale') else 'FORECAST',
        'anomaly': 'Comparison unavailable' if delta is None else f'{abs(delta):.1f}°C {"warmer" if delta>=0 else "cooler"}',
        'comparison_caption': '' if delta is None else 'than the historical average.',
        'compare_copy': f'{date_text} in Hanoi across {len(history)} previous {"leap years" if leap else "years"}.' + (' The complete 1991–2020 baseline is not available yet.' if baseline is None else ''),
        'baseline': '1991–2020 baseline unavailable' if baseline is None else f'{baseline:.1f}°C · 1991–2020 average',
        'chart_subtitle': f'{date_text} in Hanoi · {METRICS[metric].lower()} temperature in °C',
        'chart_description': f'{METRICS[metric]} · {len(history)} historical years.' + (f' Today’s forecast: {fmt(current[metric])}°C.' if current else ''),
        'table_subtitle': f'{date_text} in Hanoi · All temperatures in Celsius',
        'table_count': f'{len(history)} historical years + today',
        **{f'{k}_column': 'active-metric' if k==metric else '' for k in METRICS},
    }
    # Only fragments constructed here are allowed to contain markup.
    fragments = {}
    for key, selector in [('warmest',max),('coldest',min)]:
        row = selector(history,key=lambda r:r[metric]) if history else None
        fragments[key] = f'{fmt(row[metric])}°C<small>in {year_of(row)}</small>' if row else '—'
    fragments['years'] = f'{len(history)}<small>{"since "+str(year_of(history[0])) if history else "history not imported"}</small>'
    def page_link(selected_metric, selected_sort, selected_order, anchor=''):
        params = {'metric': selected_metric}
        if (selected_sort, selected_order) != ('year', 'desc'):
            params.update(sort=selected_sort, order=selected_order)
        return escape('/?' + urlencode(params) + anchor, quote=True)

    fragments['reset_sort'] = f'<a class="reset-sort" href="{page_link(metric, "year", "desc", "#table-title")}" title="Restore newest year first">Reset sort</a>'
    links = []
    for key, label in [('mean', 'Daily mean'), ('high', 'High'), ('low', 'Low')]:
        selected = ' aria-current="page"' if key == metric else ''
        links.append(f'<a href="{page_link(key, sort, order)}"{selected}>{label}</a>')
    fragments['metric_links'] = ''.join(links)

    headers = []
    for key, label in SORT_COLUMNS.items():
        active = key == sort
        next_order = 'asc' if active and order == 'desc' else 'desc'
        direction = 'ascending' if next_order == 'asc' else 'descending'
        aria_sort = f' aria-sort="{"ascending" if order == "asc" else "descending"}"' if active else ''
        arrow = ('↑' if order == 'asc' else '↓') if active else '↕'
        unit = ' (°C)' if key != 'year' else ''
        column_class = 'active-metric' if key == metric else ''
        headers.append(f'<th scope="col" class="{column_class}"{aria_sort}><a href="{page_link(metric, key, next_order, "#table-title")}" aria-label="Sort by {label.lower()}, {direction}">{label}{unit} <span aria-hidden="true">{arrow}</span></a></th>')
    fragments['table_headers'] = ''.join(headers)
    values['sort_description'] = f'Sorted by {SORT_COLUMNS[sort].lower()}, ' + (('oldest first' if order == 'asc' else 'newest first') if sort == 'year' else ('lowest first' if order == 'asc' else 'highest first'))

    rows = history + ([current] if current else [{'date': str(today)}])
    # Sort only the table; chart points must retain chronological order.
    value = year_of if sort == 'year' else lambda row: row.get(sort)
    available = [row for row in rows if value(row) is not None]
    missing = [row for row in rows if value(row) is None]
    ordered = sorted(available, key=lambda row: (value(row), year_of(row)), reverse=order == 'desc') + missing
    table = []
    for row in ordered:
        is_today = row['date'] == str(today)
        cells = ''.join(f'<td class="{"active-metric" if k==metric else ""}">{fmt(row.get(k))}</td>' for k in METRICS)
        status = ('Forecast' if current else 'Unavailable') if is_today else 'ERA5 estimate'
        table.append(f'<tr class="{"current-year" if is_today else ""}"><th scope="row">{year_of(row)}{" · Today" if is_today else ""}</th>{cells}<td><span class="row-status {"forecast" if is_today else ""}">{status}</span></td></tr>')
    fragments['year_rows'] = ''.join(table)
    fragments['chart'] = chart_svg(history,current,baseline,today.year,metric,leap)
    slots = {**{k:escape(str(v)) for k,v in values.items()},**fragments}
    return re.sub(r'\{\{([a-z_]+)\}\}',lambda m:slots[m[1]],PAGE)
