"""Verify a real forecast through the local API using a disposable synthetic account."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import secrets
import json
import httpx

day = datetime.now(ZoneInfo('Europe/Chisinau')).date()
with httpx.Client(base_url='http://127.0.0.1:8000', timeout=20) as client:
    response = client.post('/api/auth/register', json={'email': 'qa-'+secrets.token_hex(8)+'@example.com', 'name': 'Проверка погоды', 'password': secrets.token_urlsafe(24)})
    response.raise_for_status()
    crop = client.get('/api/crops').json()[1]
    response = client.post('/api/fields', json=dict(name='Погодный тест', area=1, latitude=47.01, longitude=28.86,
        location='Кишинёв', timezone='Europe/Chisinau', soil='Суглинок', crop_id=crop['id'],
        planting_date=(day-timedelta(days=65)).isoformat(), irrigation_type='Дождевание', efficiency=.8,
        taw=100, p=.4, initial_deficit=39, target_deficit=12, balance_start=day.isoformat()))
    response.raise_for_status()
    field_id = response.json()['id']
    response = client.post(f'/api/fields/{field_id}/weather/refresh')
    response.raise_for_status()
    result = response.json()
    report = {'source': result.get('source'), 'days': len(result['days']), 'stale': result['stale'],
              'error': result.get('error'), 'has_eto': all(d.get('eto') is not None for d in result['days']) and bool(result['days'])}
    client.post('/api/auth/logout').raise_for_status()
root = Path(__file__).resolve().parents[1]
(root / 'docs' / 'weather-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
