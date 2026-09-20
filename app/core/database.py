from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()

if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Keep the socket alive. `pool_pre_ping` only tests a connection as it is checked OUT of
    # the pool, which is exactly the case these drops are not: a grounding run holds one
    # Session open across 83 HTTP fetches, and the connection sits idle for minutes at a time
    # between statements. Cloud SQL, the Auth Proxy and any NAT in between are all free to
    # drop an idle socket, and the first thing that notices is the next INSERT, which fails
    # with "server closed the connection unexpectedly" and loses the whole run's work.
    #
    # This is not only an authoring problem. Cloud Run runs with min-instances 1, so a pooled
    # connection can sit idle overnight between student requests and fail the first request
    # that touches it.
    connect_args = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    # An hour-old connection is recycled rather than trusted; cheap insurance against a
    # server-side timeout that keepalives alone would not cover.
    pool_recycle=3600,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
