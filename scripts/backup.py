"""PostgreSQL custom-format backup. Requires running Docker Compose services."""
from pathlib import Path
from datetime import datetime, timezone
import subprocess

root = Path(__file__).resolve().parents[1]
folder = root / 'backups'
folder.mkdir(exist_ok=True)
path = folder / ('agrobalance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.dump')
temporary = path.with_suffix('.partial')
try:
    with temporary.open('xb') as output:
        subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'pg_dump', '-U', 'agrobalance', '-d', 'agrobalance', '-Fc'], cwd=root, stdout=output, check=True)
    temporary.rename(path)
    print('Backup saved:', path)
except Exception:
    temporary.unlink(missing_ok=True)
    raise
