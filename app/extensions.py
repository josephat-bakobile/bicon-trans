from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite ignores foreign keys unless told otherwise per-connection. Without
    this, deleting a parent row that still has children (e.g. via a bulk query
    that skips the ORM cascade) silently orphans them instead of failing loudly."""
    if "sqlite3" not in type(dbapi_connection).__module__:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
