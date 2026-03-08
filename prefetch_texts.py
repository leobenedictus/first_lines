"""
Pre-fetches and caches opening texts for all books in the database.

Run this once before using the review tool so every book loads instantly:

    python prefetch_texts.py
"""

import os
import sqlite3
import time

import requests

from seed_db import GUTENBERG_URLS, HEADERS, START_MARKER_RE

DB_PATH = 'instance/books.db'
CACHE_DIR = 'text_cache'
FETCH_CHARS = 8000


def fetch_and_cache(gutenberg_id):
    for url_template in GUTENBERG_URLS:
        url = url_template.format(id=gutenberg_id)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code in (200, 206):
                try:
                    raw = resp.content.decode('utf-8')
                except UnicodeDecodeError:
                    raw = resp.content.decode('latin-1')

                match = START_MARKER_RE.search(raw)
                if match:
                    raw = raw[match.end():]
                    nl = raw.find('\n')
                    if nl != -1:
                        raw = raw[nl + 1:]

                text = raw[:FETCH_CHARS]
                cache_path = os.path.join(CACHE_DIR, f'{gutenberg_id}.txt')
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                return len(text)
        except requests.RequestException:
            continue
        time.sleep(0.3)
    return None


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT gutenberg_id, title FROM book ORDER BY title").fetchall()
    conn.close()

    to_fetch = []
    for gutenberg_id, title in rows:
        cache_path = os.path.join(CACHE_DIR, f'{gutenberg_id}.txt')
        if os.path.exists(cache_path):
            if os.path.getsize(cache_path) >= FETCH_CHARS * 0.9:
                continue
        to_fetch.append((gutenberg_id, title))

    if not to_fetch:
        print("All texts already cached.")
        return

    print(f"Fetching {len(to_fetch)} book(s)...\n")
    ok = 0
    failed = []
    for i, (gutenberg_id, title) in enumerate(to_fetch, 1):
        print(f"  [{i}/{len(to_fetch)}] {title} (ID {gutenberg_id})...", end=' ', flush=True)
        result = fetch_and_cache(gutenberg_id)
        if result:
            print(f"{result:,} chars")
            ok += 1
        else:
            print("FAILED")
            failed.append(title)
        time.sleep(0.5)

    print(f"\nDone. {ok} fetched, {len(failed)} failed.")
    if failed:
        print("Failed:")
        for t in failed:
            print(f"  {t}")


if __name__ == '__main__':
    main()
