"""
Interactive sentence review tool — runs separately from the main app.

    python review_app.py

Then open http://localhost:5051 in your browser.

For each book you can:
  • Read the raw opening text from Gutenberg (cached locally after the first fetch)
  • See the currently extracted sentence highlighted in yellow
  • Select any text with your mouse and click "Save as first sentence"
  • Mark a book as reviewed / skip it

The manually_set flag is stored on the Book row so seed_db.py --reprocess
will never overwrite a sentence you've set by hand.
"""

import os
import re
import time

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from models import Book, db
from seed_db import GUTENBERG_URLS, HEADERS, START_MARKER_RE

load_dotenv()

CACHE_DIR = 'text_cache'
FETCH_CHARS = 8000  # characters of opening text to store / display

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'review-dev-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///books.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# ---------------------------------------------------------------------------
# Migration: add manually_set column if upgrading from an older DB
# ---------------------------------------------------------------------------

def ensure_schema():
    """Add manually_set column to an existing database that pre-dates the field."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(db.engine)
    if 'book' not in inspector.get_table_names():
        return  # table doesn't exist yet; db.create_all() will make it correctly
    cols = [col['name'] for col in inspector.get_columns('book')]
    if 'manually_set' not in cols:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE book ADD COLUMN manually_set BOOLEAN DEFAULT 0"))
            conn.commit()
        print("  Migrated: added manually_set column to book table.")


# ---------------------------------------------------------------------------
# Text fetching and caching
# ---------------------------------------------------------------------------

def get_opening_text(gutenberg_id):
    """
    Return the opening text for a book — from local cache if available,
    otherwise fetched from Gutenberg and saved to cache.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f'{gutenberg_id}.txt')

    if os.path.exists(cache_path):
        with open(cache_path, encoding='utf-8') as f:
            cached = f.read()
        if len(cached) >= FETCH_CHARS:
            return cached
        # Cache is shorter than current limit — re-fetch

    for url_template in GUTENBERG_URLS:
        url = url_template.format(id=gutenberg_id)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code in (200, 206):
                try:
                    raw = resp.content.decode('utf-8')
                except UnicodeDecodeError:
                    raw = resp.content.decode('latin-1')

                # Discard preamble
                match = START_MARKER_RE.search(raw)
                if match:
                    raw = raw[match.end():]
                    nl = raw.find('\n')
                    if nl != -1:
                        raw = raw[nl + 1:]

                text = raw[:FETCH_CHARS]
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                return text
        except requests.RequestException:
            continue
        time.sleep(0.3)

    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    books = Book.query.order_by(Book.manually_set, Book.title).all()
    total = len(books)
    done = sum(1 for b in books if b.manually_set)
    return render_template('review_index.html', books=books, total=total, done=done)


@app.route('/book/<int:book_id>')
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    text = get_opening_text(book.gutenberg_id)
    return jsonify({
        'id': book.id,
        'title': book.title,
        'author': book.author,
        'gutenberg_id': book.gutenberg_id,
        'sentence': book.first_sentence,
        'manually_set': book.manually_set,
        'text': text or '(Could not fetch text from Gutenberg)',
    })


@app.route('/book/<int:book_id>/save', methods=['POST'])
def save_sentence(book_id):
    book = Book.query.get_or_404(book_id)
    data = request.get_json()
    sentence = (data or {}).get('sentence', '').strip()
    if not sentence:
        return jsonify({'ok': False, 'error': 'empty sentence'}), 400
    book.first_sentence = sentence
    book.manually_set = True
    db.session.commit()
    return jsonify({'ok': True, 'sentence': sentence})


@app.route('/book/<int:book_id>/clear', methods=['POST'])
def clear_manual(book_id):
    """Remove the manual flag so seed_db.py --reprocess can overwrite this entry."""
    book = Book.query.get_or_404(book_id)
    book.manually_set = False
    db.session.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        ensure_schema()
        db.create_all()
    app.run(debug=True, port=5051)
