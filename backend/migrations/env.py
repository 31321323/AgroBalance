from alembic import context
from app.db import Base, engine
from app import models

def run():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=engine.dialect.name == 'sqlite', compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

run()
