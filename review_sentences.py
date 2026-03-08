"""
Generates review.html — a human-readable page showing, for every book in the
database, the extracted first sentence alongside the raw opening text from
Project Gutenberg (everything after the *** START OF *** marker, up to ~3 000
characters).

Use this to spot extraction errors before running the app.

Run:
    python review_sentences.py
Then open review.html in your browser.
"""

import re
import time
import html as html_lib
import requests
from app import app
from models import db, Book
from seed_db import START_MARKER_RE, FETCH_BYTES, GUTENBERG_URLS, HEADERS


def fetch_opening(gutenberg_id, chars=3000):
    """Return the raw text after the START marker (up to `chars` characters)."""
    for url_template in GUTENBERG_URLS:
        url = url_template.format(id=gutenberg_id)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code in (200, 206):
                try:
                    text = resp.content.decode('utf-8')
                except UnicodeDecodeError:
                    text = resp.content.decode('latin-1')

                match = START_MARKER_RE.search(text)
                if match:
                    after = text[match.end():]
                    newline = after.find('\n')
                    if newline != -1:
                        after = after[newline + 1:]
                    return after[:chars]
                # No START marker found — just return from the top
                return text[:chars]
        except requests.RequestException:
            continue
    return None


def highlight(raw, sentence):
    """
    Return HTML where `sentence` is wrapped in a <mark> tag if found in `raw`.
    Falls back to plain escaped text if not found.
    """
    escaped_raw = html_lib.escape(raw)
    escaped_sent = html_lib.escape(sentence)
    if escaped_sent in escaped_raw:
        return escaped_raw.replace(
            escaped_sent,
            f'<mark>{escaped_sent}</mark>',
            1,
        )
    return escaped_raw


def build_html(entries):
    rows = []
    for i, (book, opening) in enumerate(entries, 1):
        sentence = html_lib.escape(book.first_sentence)
        if opening:
            raw_html = highlight(opening, book.first_sentence)
        else:
            raw_html = '<em style="color:#aaa">Could not fetch text</em>'

        rows.append(f"""
<section id="book-{book.id}">
  <h2>{i}. {html_lib.escape(book.title)}
      <span class="meta">— {html_lib.escape(book.author)}
      &nbsp;·&nbsp; Gutenberg&nbsp;ID&nbsp;{book.gutenberg_id}</span>
  </h2>
  <div class="extracted">
    <strong>Extracted sentence:</strong><br>
    <blockquote>{sentence}</blockquote>
  </div>
  <details>
    <summary>Raw opening text (click to expand)</summary>
    <pre class="raw">{raw_html}</pre>
  </details>
</section>
""")

    body = '\n'.join(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>First Sentences — Review</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    max-width: 900px;
    margin: 2rem auto;
    padding: 0 1.5rem 4rem;
    background: #faf8f4;
    color: #1a1a1a;
  }}
  h1 {{ font-size: 1.6rem; border-bottom: 2px solid #1a1a1a; padding-bottom: .5rem; }}
  section {{
    margin: 2.5rem 0;
    padding: 1.5rem;
    background: white;
    border: 1px solid #ddd8cf;
    border-radius: 8px;
  }}
  h2 {{ font-size: 1.05rem; margin: 0 0 1rem; }}
  .meta {{ font-weight: normal; font-size: 0.85rem; color: #888; }}
  .extracted {{ margin-bottom: 1rem; font-size: 0.92rem; }}
  blockquote {{
    font-family: Georgia, serif;
    font-size: 1rem;
    line-height: 1.6;
    margin: .5rem 0 0 1rem;
    padding-left: .75rem;
    border-left: 3px solid #2c4a7c;
    color: #1a1a1a;
  }}
  details summary {{
    cursor: pointer;
    font-size: 0.85rem;
    color: #888;
    user-select: none;
  }}
  pre.raw {{
    font-family: 'Courier New', monospace;
    font-size: 0.78rem;
    line-height: 1.55;
    white-space: pre-wrap;
    background: #f5f3ef;
    padding: 1rem;
    border-radius: 4px;
    margin-top: .5rem;
    overflow-x: auto;
  }}
  mark {{
    background: #ffe066;
    padding: 0 2px;
    border-radius: 2px;
  }}
  .toc {{
    font-size: 0.85rem;
    columns: 3;
    column-gap: 1.5rem;
    margin-bottom: 2rem;
  }}
  .toc a {{ color: #2c4a7c; text-decoration: none; display: block; padding: 1px 0; }}
  .toc a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>First Sentences — Review ({len(entries)} books)</h1>
<p style="color:#888; font-size:.9rem">
  The highlighted text in each raw opening shows where the extracted sentence was found.
  If the highlight is missing, the sentence wasn't found verbatim in the first 3 000 characters.
  Raw text is collapsed by default — click to expand.
</p>

<nav class="toc">
{''.join(f'<a href="#book-{book.id}">{i}. {html_lib.escape(book.title)}</a>' for i, (book, _) in enumerate(entries, 1))}
</nav>

{body}
</body>
</html>"""


def main():
    with app.app_context():
        books = Book.query.order_by(Book.title).all()
        if not books:
            print("No books in database. Run seed_db.py first.")
            return

        print(f"Found {len(books)} books. Fetching opening text for each…\n")
        entries = []
        for i, book in enumerate(books, 1):
            print(f"  [{i}/{len(books)}] {book.title}", end=' ', flush=True)
            opening = fetch_opening(book.gutenberg_id)
            entries.append((book, opening))
            print("OK" if opening else "FAILED")
            time.sleep(0.8)

        html = build_html(entries)
        with open('review.html', 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"\nSaved review.html — open it in your browser.")


if __name__ == '__main__':
    main()
