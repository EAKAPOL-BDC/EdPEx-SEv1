"""Perform the single permitted, read-only Supabase connectivity query."""

import os
import sys

import psycopg

VARIABLES = (
    "SUPABASE_DEV_DB_HOST",
    "SUPABASE_DEV_DB_PORT",
    "SUPABASE_DEV_DB_NAME",
    "SUPABASE_DEV_DB_USER",
    "SUPABASE_DEV_DB_PASSWORD",
)


def main() -> int:
    missing = [name for name in VARIABLES if not os.getenv(name)]
    if missing:
        print("Supabase connection check failed: required secret is missing.", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(
            host=os.environ["SUPABASE_DEV_DB_HOST"],
            port=os.environ["SUPABASE_DEV_DB_PORT"],
            dbname=os.environ["SUPABASE_DEV_DB_NAME"],
            user=os.environ["SUPABASE_DEV_DB_USER"],
            password=os.environ["SUPABASE_DEV_DB_PASSWORD"],
            sslmode="require",
            connect_timeout=10,
            options="-c default_transaction_read_only=on",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise RuntimeError("Unexpected health-check result")
    except Exception as error:
        # Deliberately omit exception text: drivers may include connection details.
        print(f"Supabase connection check failed ({type(error).__name__}).", file=sys.stderr)
        return 1

    print("Supabase connection check passed (read-only SELECT 1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
