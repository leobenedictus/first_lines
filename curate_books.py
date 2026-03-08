"""
Builds a list of ~140 English-language novels from Project Gutenberg using
the Gutendex API (https://gutendex.com).

Strategy:
  - A handful of famous titles are included deliberately (so people encounter
    some they know, but not many).
  - The rest are drawn from topic searches across different genres, filtered
    to exclude the most heavily downloaded titles (which tend to be the most
    famous/recognisable).
  - Books with very few downloads are excluded too — they're often incomplete
    transcriptions or non-fiction.

Run once before seed_db.py:
    python curate_books.py

Output: books.json
"""

import json
import time
import requests

GUTENDEX_BASE = "https://gutendex.com/books"
TARGET = 140

# Minimum and maximum download counts to include.
# Too low = likely a broken/obscure text. Too high (and not in FAMOUS_IDS) = too recognisable.
MIN_DOWNLOADS = 800
MAX_DOWNLOADS_FOR_UNKNOWN = 80_000

# Gutenberg IDs to include regardless of download count (the deliberate famous ones)
FAMOUS_IDS = [1342, 11, 84, 2701, 1400, 174, 76, 345, 98, 768, 215, 2852]

# Topics to query on Gutendex (searches both subjects and bookshelves)
TOPICS = [
    "adventure",
    "detective fiction",
    "gothic fiction",
    "science fiction",
    "sea stories",
    "historical fiction",
    "western stories",
    "war stories",
    "mystery",
    "romance",
    "satire",
    "humour",
    "colonial fiction",
    "frontier fiction",
    "psychological fiction",
]


def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(1)


def book_from_gutendex(item):
    """Extract a clean book dict from a Gutendex result item."""
    if not item.get('authors'):
        return None
    # Must have a plain-text download
    if not any('text/plain' in fmt for fmt in item.get('formats', {}).keys()):
        return None
    author = item['authors'][0]['name']
    return {
        'gutenberg_id': item['id'],
        'title': item['title'],
        'author': author,
    }


def fetch_famous():
    """Fetch metadata for the explicitly included famous books."""
    books = []
    for gid in FAMOUS_IDS:
        try:
            data = fetch_json(f"{GUTENDEX_BASE}/{gid}/")
            book = book_from_gutendex(data)
            if book:
                books.append(book)
                print(f"  [famous] {book['title']}")
        except Exception as e:
            print(f"  [famous] FAILED id={gid}: {e}")
        time.sleep(0.3)
    return books


def fetch_by_topic(topic, seen_ids, max_per_topic=15):
    """Fetch books for a given topic, skipping already-seen IDs and very famous titles."""
    books = []
    url = f"{GUTENDEX_BASE}/?topic={topic}&languages=en"
    pages = 0

    while url and len(books) < max_per_topic and pages < 4:
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"  [topic:{topic}] request failed: {e}")
            break

        for item in data.get('results', []):
            if item['id'] in seen_ids:
                continue
            downloads = item.get('download_count', 0)
            if downloads < MIN_DOWNLOADS:
                continue
            if downloads > MAX_DOWNLOADS_FOR_UNKNOWN and item['id'] not in FAMOUS_IDS:
                continue
            book = book_from_gutendex(item)
            if book:
                books.append(book)
                seen_ids.add(item['id'])

        url = data.get('next')
        pages += 1
        time.sleep(0.4)

    return books


def main():
    print("Fetching famous titles...")
    seen_ids = set(FAMOUS_IDS)
    all_books = fetch_famous()
    seen_ids.update(b['gutenberg_id'] for b in all_books)

    print(f"\nFetching by topic (target: {TARGET} total)...")
    for topic in TOPICS:
        if len(all_books) >= TARGET:
            break
        print(f"  Topic: '{topic}'")
        topic_books = fetch_by_topic(topic, seen_ids, max_per_topic=15)
        for b in topic_books:
            if len(all_books) >= TARGET:
                break
            all_books.append(b)
            print(f"    + {b['title']} ({b['gutenberg_id']})")
        time.sleep(0.5)

    print(f"\nTotal collected: {len(all_books)} books")

    with open('books.json', 'w', encoding='utf-8') as f:
        json.dump(all_books, f, indent=2, ensure_ascii=False)

    print("Saved to books.json")
    print("\nReview books.json, then run: python seed_db.py")


if __name__ == '__main__':
    main()
