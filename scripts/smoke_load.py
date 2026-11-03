"""Local read-concurrency smoke test; not a production capacity benchmark."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import time
import httpx

with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30, limits=httpx.Limits(max_connections=60)) as client:
    response = client.post('/api/auth/demo')
    response.raise_for_status()
    def read(_):
        start = time.perf_counter()
        response = client.get('/api/fields')
        response.raise_for_status()
        assert len(response.json()) == 3
        return time.perf_counter() - start
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=50) as executor:
        timings = sorted(executor.map(read, range(50)))
    result = {'requests': 50, 'concurrency': 50, 'scope': 'GET /api/fields, one demo account, SQLite, localhost',
              'total_seconds': round(time.perf_counter()-start, 3),
              'median_seconds': round(timings[24], 3), 'p95_seconds': round(timings[47], 3),
              'max_seconds': round(timings[-1], 3)}
    client.post('/api/auth/logout').raise_for_status()
root = Path(__file__).resolve().parents[1]
(root / 'docs' / 'load-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
