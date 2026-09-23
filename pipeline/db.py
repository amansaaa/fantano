"""MySQL connection helper shared by every pipeline stage to get database connections."""

import os
from pathlib import Path    # object oriented way to work with filesystme paths

import pymysql
from dotenv import load_dotenv

# Finds .env file and loads its conents into environment variables
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def connect() -> pymysql.connections.Connection:
    """Open a new connection to the fantano database, configured from .env."""
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",                      # every client that calls connect must be uft8mb4 to avoid name mismatches
        cursorclass=pymysql.cursors.DictCursor,  # cursor (object used to run SQL and fetch results) naturally returns tuples, instead returns dict so indexing by name rather than position
        autocommit=False,                       # stages are atomicity compliant (half completed transaction don't get saved)
    )

if __name__ == "__main__":  # Only sets __name__ to __main__ for file we run directly (importing elsewhere skips it)
    # conn is the connection to mysql and cur is the cursor (object we run SQL through)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT CURRENT_USER() AS user, VERSION() AS version")
        print(cur.fetchone())
        cur.execute("SHOW TABLES")
        print(f"{len(cur.fetchall())} tables")
