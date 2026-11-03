"""Package deliverables, excluding secrets, runtime databases and dependencies."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
archive = root / 'AgroBalance-source.zip'
folders = ['backend', 'frontend', 'docs', 'scripts']
root_files = ['README.md', 'Dockerfile', 'docker-compose.yml', 'Caddyfile', '.env.example', '.gitignore', '.dockerignore', 'start-local.ps1']
excluded = {'node_modules', '__pycache__', '.pytest_cache', '.venv', '.pnpm-store'}
paths = [root / name for name in root_files]
for folder in folders:
    paths.extend(p for p in (root / folder).rglob('*') if p.is_file() and not any(part in excluded for part in p.relative_to(root).parts) and p.suffix not in {'.pyc', '.tsbuildinfo', '.db'} and p.name != '.env')
with ZipFile(archive, 'w', ZIP_DEFLATED) as output:
    for path in sorted(paths):
        output.write(path, 'AgroBalance/' + path.relative_to(root).as_posix())
print(archive.name, archive.stat().st_size, 'bytes')
