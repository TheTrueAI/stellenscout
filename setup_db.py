#!/usr/bin/env python3
"""Initialize the StellenScout Supabase database tables.

Verifies that the required tables exist and prints any missing schema
that needs to be created via the Supabase SQL Editor.

Usage:
    python setup_db.py
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# The SQL to run in Supabase SQL Editor if tables don't exist yet.
SETUP_SQL = """\
-- ── subscribers ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscribers (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    email               TEXT NOT NULL UNIQUE,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    confirmation_token  TEXT,
    token_expires_at    TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_subscribers_token
    ON subscribers (confirmation_token) WHERE confirmation_token IS NOT NULL;

-- ── jobs ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    location    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── job_sent_logs ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_sent_logs (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id   UUID NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subscriber_id, job_id)
);
"""

MIGRATION_SQL = """\
-- ── Migration: add Double Opt-In columns to subscribers ─────────────
ALTER TABLE subscribers
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS confirmation_token TEXT,
  ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ;
ALTER TABLE subscribers ALTER COLUMN is_active SET DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_subscribers_token
    ON subscribers (confirmation_token) WHERE confirmation_token IS NOT NULL;
-- Existing subscribers stay active:
UPDATE subscribers SET is_active = TRUE WHERE is_active IS NULL;
"""

REQUIRED_TABLES = ["subscribers", "jobs", "job_sent_logs"]


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY environment variables.")
        return 1

    client = create_client(url, key)

    print("Checking Supabase tables …\n")
    all_ok = True
    for table in REQUIRED_TABLES:
        try:
            client.table(table).select("*").limit(1).execute()
            print(f"  ✓ {table}")
        except Exception as e:
            print(f"  ✗ {table}  — {e}")
            all_ok = False

    if all_ok:
        print("\nAll tables exist. You're good to go!")
        print("\n" + "=" * 60)
        print("If upgrading, run this migration SQL in the Supabase SQL Editor:\n")
        print(MIGRATION_SQL)
        print("=" * 60)
        return 0

    print("\n" + "=" * 60)
    print("Some tables are missing. Run the following SQL in the")
    print("Supabase SQL Editor (https://supabase.com/dashboard):\n")
    print(SETUP_SQL)
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
