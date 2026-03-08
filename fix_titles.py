"""
Fixes two common title problems from Gutendex/Gutenberg catalog data:

  1. MARC subfield codes — e.g. "Billy Budd : $b and other prose pieces"
     becomes "Billy Budd"

  2. Inconsistent casing — e.g. "The call of the wild" becomes
     "The Call of the Wild"

  3. Very long subtitles — stripped if the portion after : or ; exceeds
     80 characters (e.g. the multi-line Pym subtitle)

Usage:
    python fix_titles.py          # show proposed changes, don't apply them
    python fix_titles.py --fix    # apply changes to the database
"""

import re
import sys
import sqlite3

DB_PATH = 'instance/books.db'

# Words that stay lowercase in the middle of a title
LOWERCASE_WORDS = {
    'a', 'an', 'the',
    'and', 'but', 'or', 'nor', 'for', 'so', 'yet',
    'at', 'by', 'in', 'of', 'on', 'to', 'up', 'as', 'is', 'it',
}

MAX_SUBTITLE_CHARS = 80   # strip subtitle if the part after : or ; exceeds this


# ---------------------------------------------------------------------------
# Cleaning steps
# ---------------------------------------------------------------------------

def strip_marc(title):
    """Remove MARC $b subfield codes."""
    title = re.sub(r'\s*[:;]\s*\$b\b.*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*\$b\b.*', '', title, flags=re.IGNORECASE)
    return title.strip().rstrip(':;').strip()


def strip_long_subtitle(title):
    """Remove subtitles that are excessively long (probably Gutenberg catalog noise)."""
    for sep in [':', ';']:
        idx = title.find(sep)
        if idx != -1 and len(title[idx + 1:].strip()) > MAX_SUBTITLE_CHARS:
            return title[:idx].strip()
    return title


def _cap_word(word):
    """Capitalise the first letter, preserve the rest."""
    if not word:
        return word
    # Already has uppercase beyond position 0 → probably an acronym, leave it
    if len(word) > 1 and any(c.isupper() for c in word[1:]):
        return word
    return word[0].upper() + word[1:]


def smart_title_case(title):
    """
    Apply title-case rules:
    - Always capitalise the first and last words.
    - Capitalise the first word after a colon, semicolon, or dash.
    - Leave articles / short prepositions / conjunctions lowercase mid-title.
    - Capitalise everything else.
    """
    # Tokenise into (word, separator) pairs, preserving original spacing
    tokens = re.findall(r'[^\s;:—–\-]+|[\s;:—–\-]+', title)

    words = [t for t in tokens if t.strip() and not re.match(r'^[;:—–\-\s]+$', t)]
    total_words = len(words)
    word_idx = 0
    capitalise_next = True
    result = []

    for token in tokens:
        is_separator = bool(re.match(r'^[\s;:—–\-]+$', token))

        if is_separator:
            result.append(token)
            if re.search(r'[;:—–\-]', token):
                capitalise_next = True
        else:
            word_idx += 1
            is_last = (word_idx == total_words)
            bare = re.sub(r'[^a-zA-Z]', '', token).lower()

            if capitalise_next or is_last:
                result.append(_cap_word(token))
                capitalise_next = False
            elif bare in LOWERCASE_WORDS:
                result.append(token.lower())
            else:
                result.append(_cap_word(token))

    return ''.join(result)


def needs_title_case(title):
    """
    True if any significant word (>= 4 letters, not a stop word) after the
    first word is all-lowercase — suggesting the title wasn't properly cased.
    """
    words = re.split(r'[\s;:—–\-,]+', title)
    for word in words[1:]:
        bare = re.sub(r'[^a-zA-Z]', '', word)
        if (len(bare) >= 4
                and bare.lower() not in LOWERCASE_WORDS
                and bare == bare.lower()):
            return True
    return False


def clean_title(title):
    """Apply all fixes in order."""
    t = strip_marc(title)
    t = strip_long_subtitle(t)
    if needs_title_case(t):
        t = smart_title_case(t)
    return t


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    fix = '--fix' in sys.argv

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, title FROM book ORDER BY title").fetchall()

    changes = []
    for db_id, title in rows:
        cleaned = clean_title(title)
        if cleaned != title:
            changes.append((db_id, title, cleaned))

    if not changes:
        print("No title changes needed.")
        conn.close()
        return

    print(f"{len(changes)} title(s) to update:\n")
    for _, old, new in changes:
        print(f"  BEFORE: {old}")
        print(f"  AFTER:  {new}")
        print()

    if fix:
        for db_id, _, new in changes:
            conn.execute("UPDATE book SET title = ? WHERE id = ?", (new, db_id))
        conn.commit()
        print(f"Applied {len(changes)} title fix(es).")
    else:
        print("Run with --fix to apply these changes.")

    conn.close()


if __name__ == '__main__':
    main()
