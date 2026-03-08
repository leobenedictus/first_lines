"""
One-time script to copy books from local SQLite into a remote PostgreSQL database.

Usage:
    DATABASE_URL=postgresql://... python migrate_to_postgres.py

The DATABASE_URL is shown in Railway under your Postgres plugin → Connect tab.
"""

import os
import sqlite3
import sys

# Must be set before importing app/models
db_url = os.environ.get('DATABASE_URL', '')
if not db_url or 'sqlite' in db_url:
    print("Set DATABASE_URL to your Railway PostgreSQL URL before running this script.")
    sys.exit(1)

if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
os.environ['DATABASE_URL'] = db_url

from app import app
from models import db, Book

SQLITE_PATH = 'instance/books.db'

def main():
    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute(
        "SELECT gutenberg_id, title, author, first_sentence, elo, wins, losses, manually_set "
        "FROM book ORDER BY id"
    ).fetchall()
    conn.close()

    print(f"Found {len(rows)} books in local SQLite database.")

    with app.app_context():
        db.create_all()
        existing = {b.gutenberg_id for b in Book.query.all()}
        added = 0
        for gid, title, author, sentence, elo, wins, losses, manually_set in rows:
            if gid in existing:
                print(f"  [skip] {title}")
                continue
            book = Book(
                gutenberg_id=gid,
                title=title,
                author=author,
                first_sentence=sentence,
                elo=elo or 1000.0,
                wins=wins or 0,
                losses=losses or 0,
                manually_set=bool(manually_set),
            )
            db.session.add(book)
            added += 1
        db.session.commit()

    print(f"Done. {added} books added to PostgreSQL.")

if __name__ == '__main__':
    main()
