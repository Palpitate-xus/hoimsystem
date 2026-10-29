"""Keep unqualified PostgreSQL URLs on the deployment's installed DBAPI."""


def normalize_database_url(database_url: str) -> str:
    """Make psycopg2 explicit without re-encoding credentials or query options."""
    scheme, separator, remainder = database_url.partition("://")
    if separator and scheme.lower() in {"postgres", "postgresql"}:
        return "postgresql+psycopg2://" + remainder
    return database_url
