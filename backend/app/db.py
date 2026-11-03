import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///' + str(ROOT / 'agrobalance.db').replace('\\', '/'))
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}, pool_pre_ping=True)
if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_settings(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=10000')

class Base(DeclarativeBase):
    pass

SessionLocal = sessionmaker(engine, expire_on_commit=False)

def get_db():
    with SessionLocal() as db:
        yield db
