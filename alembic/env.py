from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool
from app.core.config import get_settings
from app.core.database import Base
import app.models.entities  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # Build directly from the settings URL. Passing a URL through Alembic's
    # ConfigParser can reinterpret percent-encoded password characters and
    # silently change credentials for Cloud SQL URLs.
    connectable = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
