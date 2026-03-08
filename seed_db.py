"""
Fetches book texts from Project Gutenberg, extracts the first sentence of each,
and populates the database.

Run after curate_books.py:
    python seed_db.py

Safe to re-run: books already in the database are skipped.
To re-extract sentences for all books (e.g. after improving the extractor):
    python seed_db.py --reprocess
"""

import json
import re
import sys
import time

import nltk
import requests

nltk.download('punkt_tab', quiet=True)
from nltk.tokenize import sent_tokenize

from app import app
from models import db, Book

# Fetch the first 96 KB — enough to get past long prefaces.
FETCH_BYTES = 98_304

GUTENBERG_URLS = [
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}-0.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
]

HEADERS = {
    'User-Agent': 'first-sentences-research/1.0 (educational project)',
    'Range': f'bytes=0-{FETCH_BYTES}',
}

START_MARKER_RE = re.compile(
    r'\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG',
    re.IGNORECASE,
)

# Headings that indicate a section we should skip entirely (preface, foreword, etc.)
# If an all-caps heading line contains one of these words, skip the whole paragraph.
SKIP_SECTION_RE = re.compile(
    r'\b(preface|foreword|introduction|acknowledgements?|dedication|'
    r'editorial|translator|prologue|author\'s note|a note|note to|'
    r'by way of|prefatory|advertisement)\b',
    re.IGNORECASE,
)

# Sentence-level patterns that mark front matter rather than prose
FRONT_MATTER_SENTENCE_RE = re.compile(
    r'^(copyright|all rights|published|first published|printed in|'
    r'new impression|new edition|impression|edition\b|transcribed|'
    r'produced by|scanned|this (story|novel|book|tale|sketch|piece|volume)|'
    r'the (following|author|editor|translator|present)\b)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Sentence-level prose check
# ---------------------------------------------------------------------------

def is_prose_sentence(sent):
    """
    Returns True if a sentence looks like genuine narrative prose rather than
    front matter (titles, headings, publisher info, editorial notes, etc.).

    Checks applied (any failure → return False):
      - Length between 20 and 600 chars, at least 6 words
      - Not entirely uppercase
      - Does not start with a coordinating conjunction (mid-narrative signal)
      - Does not match known front-matter patterns
      - Does not start with all-caps words (chapter heading merged into paragraph)
      - Proportion of title-cased non-first words ≤ 55 %
    """
    sent = sent.strip()

    if len(sent) < 20 or len(sent) > 600:
        return False

    words = sent.split()
    if len(words) < 6:
        return False

    # All-caps sentence → heading
    if sent.upper() == sent:
        return False

    # Known front-matter pattern
    if FRONT_MATTER_SENTENCE_RE.match(sent):
        return False

    # First word(s) are all-caps → chapter heading not yet stripped
    # (e.g. "THE MESSENGER Peter Blood, bachelor of…")
    first_two = ' '.join(words[:2])
    if re.match(r'^[A-Z]{2}[A-Z\s]*$', first_two):
        return False

    # Title-case ratio among non-first words
    non_first = [re.sub(r'[^a-zA-Z]', '', w) for w in words[1:]]
    non_first = [w for w in non_first if len(w) >= 2]
    if len(non_first) >= 3:
        title_cased = sum(1 for w in non_first if w[0].isupper())
        if title_cased / len(non_first) > 0.55:
            return False

    return True


# ---------------------------------------------------------------------------
# Paragraph-level processing
# ---------------------------------------------------------------------------

def process_paragraph(para):
    """
    Given a raw paragraph block, separate out all-caps heading lines from
    prose lines. Returns (heading, prose_text).

    heading  – joined heading line(s), used to decide whether to skip the section
    prose_text – the remaining lines flattened to a single string
    """
    heading_parts = []
    prose_parts = []

    for line in para.split('\n'):
        s = line.strip()
        if not s:
            continue
        # All-caps line, short enough to be a heading (≤ 80 chars)
        if s == s.upper() and len(s) <= 80 and re.search(r'[A-Z]', s):
            heading_parts.append(s)
        else:
            prose_parts.append(s)

    heading = ' '.join(heading_parts).strip()
    prose_text = re.sub(r'\s+', ' ', ' '.join(prose_parts)).strip()
    return heading, prose_text


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_first_sentence(raw_text):
    """
    Returns the first sentence of actual prose from a Gutenberg plain-text file,
    or None if extraction fails.

    Algorithm:
      1. Discard everything before the *** START OF *** marker.
      2. Split the remainder into blank-line-separated paragraphs.
      3. For each paragraph:
           a. Separate all-caps heading lines from prose lines.
           b. If the heading marks a preface / foreword / note → skip entirely.
           c. Apply quick prose plausibility checks to the prose text.
           d. Tokenise and walk the sentences; return the first that passes
              is_prose_sentence().
    """
    if not raw_text:
        return None

    # Step 1: discard Gutenberg preamble
    match = START_MARKER_RE.search(raw_text)
    if match:
        raw_text = raw_text[match.end():]
        newline = raw_text.find('\n')
        if newline != -1:
            raw_text = raw_text[newline + 1:]

    # Step 2: split into paragraphs
    paragraphs = re.split(r'\n[ \t]*\n', raw_text)

    for para in paragraphs:
        heading, text = process_paragraph(para)

        # Step 3b: skip front-matter sections (preface, foreword, etc.)
        if heading and SKIP_SECTION_RE.search(heading):
            continue

        # Step 3c: quick paragraph plausibility
        if len(text) < 40:
            continue
        if not re.search(r'[.!?]', text):
            continue
        alpha = [c for c in text if c.isalpha()]
        if alpha and sum(1 for c in alpha if c.islower()) / len(alpha) < 0.35:
            continue

        # Step 3d: tokenise and find first prose sentence
        try:
            sentences = sent_tokenize(text)
        except Exception:
            continue

        for sent in sentences:
            if is_prose_sentence(sent):
                return sent.strip()

    return None


# ---------------------------------------------------------------------------
# Gutenberg fetch
# ---------------------------------------------------------------------------

def fetch_text(gutenberg_id):
    for url_template in GUTENBERG_URLS:
        url = url_template.format(id=gutenberg_id)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code in (200, 206):
                try:
                    return resp.content.decode('utf-8')
                except UnicodeDecodeError:
                    return resp.content.decode('latin-1')
        except requests.RequestException:
            continue
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    reprocess = '--reprocess' in sys.argv

    if not __import__('os').path.exists('books.json'):
        print("books.json not found. Run curate_books.py first.")
        sys.exit(1)

    with open('books.json', encoding='utf-8') as f:
        books_data = json.load(f)

    print(f"Loaded {len(books_data)} books from books.json")
    if reprocess:
        print("--reprocess flag set: re-extracting sentences for all books\n")
    else:
        print()

    with app.app_context():
        db.create_all()

        successes = 0
        failures = []

        for book_data in books_data:
            gid = book_data['gutenberg_id']
            title = book_data['title']
            author = book_data['author']

            existing = Book.query.filter_by(gutenberg_id=gid).first()

            if existing and not reprocess:
                print(f"  [skip]  {title}")
                successes += 1
                continue

            print(f"  [fetch] {title} (ID {gid}) ...", end=' ', flush=True)

            text = fetch_text(gid)
            if not text:
                print("FAILED (could not fetch text)")
                failures.append({'id': gid, 'title': title, 'reason': 'fetch failed'})
                time.sleep(0.5)
                continue

            sentence = extract_first_sentence(text)
            if not sentence:
                print("FAILED (could not extract sentence)")
                failures.append({'id': gid, 'title': title, 'reason': 'extraction failed'})
                time.sleep(0.5)
                continue

            if existing:
                existing.first_sentence = sentence
                db.session.commit()
                print(f'UPDATED — "{sentence[:80]}{"…" if len(sentence) > 80 else ""}"')
            else:
                book = Book(
                    gutenberg_id=gid,
                    title=title,
                    author=author,
                    first_sentence=sentence,
                )
                db.session.add(book)
                db.session.commit()
                print(f'OK — "{sentence[:80]}{"…" if len(sentence) > 80 else ""}"')

            successes += 1
            time.sleep(1.2)  # polite delay between Gutenberg requests

        print(f"\n{'='*60}")
        print(f"Done. {successes} books processed, {len(failures)} failed.")
        if failures:
            print("\nFailed books:")
            for f in failures:
                print(f"  {f['id']:>6}  {f['title']}  [{f['reason']}]")


if __name__ == '__main__':
    main()
