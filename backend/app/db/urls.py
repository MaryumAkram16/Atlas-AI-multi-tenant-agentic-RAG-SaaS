from sqlalchemy.engine import make_url


def sqlalchemy_url(url: str) -> str:
    """postgresql://... -> postgresql+psycopg://... for SQLAlchemy/Alembic."""
    u = make_url(url)
    if u.drivername in ("postgresql", "postgres"):
        u = u.set(drivername="postgresql+psycopg")
    return u.render_as_string(hide_password=False)


def libpq_url(url: str) -> str:
    """postgresql+psycopg://... -> postgresql://... for psycopg."""
    u = make_url(url)
    return u.set(drivername="postgresql").render_as_string(hide_password=False)
