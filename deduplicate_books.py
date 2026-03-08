"""
Checks books.json and the database for duplicate books.

Duplicates are matched on normalised title alone (lowercase, no articles,
no subtitles). When duplicates are found, the entry with the LOWEST Gutenberg
ID is kept — lower IDs are generally the canonical Gutenberg transcription.

Usage:
    python deduplicate_books.py           # report only — shows what would change
    python deduplicate_books.py --fix     # removes duplicates from books.json + DB
    python deduplicate_books.py --list    # print every book in the DB (sorted by title)
"""

import json
import os
import re
import sys

from app import app
from models import db, Book


def normalise(title):
    """Return a simplified title key for duplicate matching."""
    t = title.lower().strip()
    t = re.sub(r'^(the|a|an)\s+', '', t)      # strip leading articles
    t = re.sub(r'\s*[:;].*$', '', t)           # strip subtitles after colon/semicolon
    t = re.sub(r'[-—–]', ' ', t)              # replace all dashes with spaces
    t = re.sub(r'[^a-z0-9 ]', '', t)          # strip remaining punctuation
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def find_duplicate_groups(entries):
    """
    Group entries by normalised title.
    Returns a list of groups that contain more than one entry.
    """
    groups = {}
    for entry in entries:
        key = normalise(entry['title'])
        groups.setdefault(key, []).append(entry)
    return [g for g in groups.values() if len(g) > 1]


def report_and_collect(groups, id_field='gutenberg_id'):
    """Print duplicate groups and return the IDs to remove."""
    to_remove = []
    for group in groups:
        group.sort(key=lambda e: e[id_field])
        keep = group[0]
        remove = group[1:]
        print(f"  KEEP   {id_field}={keep[id_field]}  \"{keep['title']}\"")
        for e in remove:
            print(f"  REMOVE {id_field}={e[id_field]}  \"{e['title']}\"")
            to_remove.append(e[id_field])
        print()
    return to_remove


def main():
    fix  = '--fix'  in sys.argv
    list_mode = '--list' in sys.argv

    # ------------------------------------------------------------------ #
    # --list: show every book in the DB
    # ------------------------------------------------------------------ #
    if list_mode:
        with app.app_context():
            books = Book.query.order_by(Book.title).all()
            print(f"{len(books)} books in database:\n")
            for b in books:
                print(f"  {b.gutenberg_id:>6}  {b.title}  ({b.author})")
        return

    # ------------------------------------------------------------------ #
    # 1. books.json
    # ------------------------------------------------------------------ #
    json_entries = []
    if not os.path.exists('books.json'):
        print("books.json not found — skipping.\n")
    else:
        with open('books.json', encoding='utf-8') as f:
            json_entries = json.load(f)
        print(f"books.json: {len(json_entries)} entries")

        json_groups = find_duplicate_groups(json_entries)
        if not json_groups:
            print("books.json: no duplicates.\n")
        else:
            print(f"books.json: {len(json_groups)} duplicate group(s):\n")
            ids_to_drop = report_and_collect(json_groups)

            if fix:
                cleaned = [e for e in json_entries if e['gutenberg_id'] not in ids_to_drop]
                with open('books.json', 'w', encoding='utf-8') as f:
                    json.dump(cleaned, f, indent=2, ensure_ascii=False)
                print(f"  books.json: removed {len(ids_to_drop)} entr{'y' if len(ids_to_drop)==1 else 'ies'}.\n")

    # ------------------------------------------------------------------ #
    # 2. Database
    # ------------------------------------------------------------------ #
    with app.app_context():
        db_books = Book.query.order_by(Book.gutenberg_id).all()
        if not db_books:
            print("Database is empty.")
            return

        print(f"Database: {len(db_books)} books")

        db_entries = [
            {'gutenberg_id': b.gutenberg_id, 'title': b.title,
             'author': b.author, '_db_id': b.id}
            for b in db_books
        ]

        # Match by normalised title
        db_groups = find_duplicate_groups(db_entries)

        if not db_groups:
            print("Database: no duplicates.\n")
        else:
            print(f"Database: {len(db_groups)} duplicate group(s):\n")

            db_ids_to_drop = []
            for group in db_groups:
                group.sort(key=lambda e: e['gutenberg_id'])
                keep = group[0]
                remove = group[1:]
                print(f"  KEEP   gutenberg_id={keep['gutenberg_id']}  \"{keep['title']}\"")
                for e in remove:
                    print(f"  REMOVE gutenberg_id={e['gutenberg_id']}  \"{e['title']}\"")
                    db_ids_to_drop.append(e['_db_id'])
                print()

            if fix:
                for db_id in db_ids_to_drop:
                    book = Book.query.get(db_id)
                    if book:
                        db.session.delete(book)
                db.session.commit()
                print(f"  Database: removed {len(db_ids_to_drop)} duplicate(s).\n")

    if not fix:
        print("Run with --fix to remove duplicates.")


if __name__ == '__main__':
    main()
