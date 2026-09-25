"""the one place that knows how to connect to MySQL. every pipeline stage imports connect() from here.

it reads the connection settings from the repo's .env file (the same file docker compose and the
web app use), so nothing about the database is hardcoded anywhere else.

usage in a stage:
    from db import connect

    with connect() as conn:                  # the connection closes when the block ends
        with conn.cursor() as cur:
            cur.execute("SELECT id, title FROM videos WHERE captions_status = %s", ("pending",))
            rows = cur.fetchall()            # [{"id": "abc123XYZ00", "title": "..."}, ...]
        conn.commit()                        # nothing is saved until you commit

quick health check:  uv run db.py
"""

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# find .env next to the repo root (one folder up from pipeline/), no matter where the script runs from
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def connect() -> pymysql.connections.Connection:
    """opens a new connection to the fantano database using the MYSQL_* settings in .env.

    os.environ[...] (not .get) on purpose: if a setting is missing you get a clear KeyError
    right away, instead of a confusing "access denied" later on.
    """
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        # the server is utf8mb4 but every client has to say so too, or "Beyoncé" comes back mangled
        charset="utf8mb4",
        # rows come back as dicts (row["title"]) instead of tuples (row[1]), so adding a column
        # to a SELECT never quietly shifts everything else around
        cursorclass=pymysql.cursors.DictCursor,
        # nothing is saved until a stage calls commit(). if a stage crashes halfway through a
        # video, that video's half-written rows just get thrown away
        autocommit=False,
    )


def print_health_check() -> None:
    """prints who we're connected as, the MySQL version, and how many tables exist.
    if it says 0 tables, the database is up but db/schema.sql never ran."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT CURRENT_USER() AS user, VERSION() AS version")
        print(cur.fetchone())
        cur.execute("SHOW TABLES")
        print(f"{len(cur.fetchall())} tables")


# only runs for `uv run db.py`, not when another file imports connect()
if __name__ == "__main__":
    print_health_check()
