"""Create .env without overwriting an existing configuration."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('.env already exists; nothing changed.')
else:
    content = (root / '.env.example').read_text(encoding='utf-8')
    content = content.replace('replace_with_random_url_safe_password', secrets.token_urlsafe(36))
    target.write_text(content, encoding='utf-8')
    print('Created .env with a random database password. Keep this file private.')
