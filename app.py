import csv
import io
import os
import random
import uuid

from dotenv import load_dotenv
from flask import (Flask, Response, redirect, render_template,
                   request, session, url_for)

from models import Book, Comparison, db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
# Railway provides postgres:// but SQLAlchemy requires postgresql://
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///books.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

db.init_app(app)

with app.app_context():
    db.create_all()

ELO_K = 32


# ---------------------------------------------------------------------------
# Elo helpers
# ---------------------------------------------------------------------------

def _expected(rating_a, rating_b):
    return 1.0 / (1 + 10 ** ((rating_b - rating_a) / 400.0))


def update_elo(winner, loser):
    exp_w = _expected(winner.elo, loser.elo)
    exp_l = _expected(loser.elo, winner.elo)
    winner.elo += ELO_K * (1 - exp_w)
    loser.elo += ELO_K * (0 - exp_l)
    winner.wins += 1
    loser.losses += 1


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def ensure_session():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    if 'comparison_count' not in session:
        session['comparison_count'] = 0
    if 'seen_pairs' not in session:
        session['seen_pairs'] = []


def get_comparison_pair():
    """Return two books the session hasn't recently compared."""
    # seen_pairs is a list of [id_a, id_b] lists (JSON-serialisable)
    recent = set(tuple(p) for p in session.get('seen_pairs', []))

    books = Book.query.all()
    if len(books) < 2:
        return None, None

    for _ in range(150):
        a, b = random.sample(books, 2)
        pair = tuple(sorted([a.id, b.id]))
        if pair not in recent:
            return a, b

    # If somehow everything is in recent (very unlikely), just pick at random
    a, b = random.sample(books, 2)
    return a, b


def record_seen(book_a_id, book_b_id):
    seen = session.get('seen_pairs', [])
    seen.append(sorted([book_a_id, book_b_id]))
    session['seen_pairs'] = seen[-30:]   # keep last 30 to avoid cookie bloat
    session.modified = True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    ensure_session()
    book_a, book_b = get_comparison_pair()
    count = session.get('comparison_count', 0)

    if book_a is None:
        return render_template('error.html',
                               message="The database isn't ready yet. "
                                       "Please run seed_db.py first.")

    total_comparisons = Comparison.query.count()

    return render_template('compare.html',
                           book_a=book_a,
                           book_b=book_b,
                           count=count,
                           total_comparisons=total_comparisons)


@app.route('/vote', methods=['POST'])
def vote():
    ensure_session()

    # Honeypot — bots fill this in, humans don't see it
    if request.form.get('website', ''):
        return redirect(url_for('index'))

    winner_id = request.form.get('winner_id', type=int)
    book_a_id = request.form.get('book_a_id', type=int)
    book_b_id = request.form.get('book_b_id', type=int)

    if not all([winner_id, book_a_id, book_b_id]):
        return redirect(url_for('index'))

    book_a = Book.query.get(book_a_id)
    book_b = Book.query.get(book_b_id)

    if not book_a or not book_b:
        return redirect(url_for('index'))

    winner = book_a if winner_id == book_a_id else book_b
    loser = book_b if winner_id == book_a_id else book_a

    # Record comparison
    comp = Comparison(
        book_a_id=book_a_id,
        book_b_id=book_b_id,
        winner_id=winner.id,
        session_id=session['session_id'],
    )
    db.session.add(comp)

    # Update Elo
    update_elo(winner, loser)
    db.session.commit()

    # Update session
    session['comparison_count'] = session.get('comparison_count', 0) + 1
    record_seen(book_a_id, book_b_id)

    return redirect(url_for('index'))


@app.route('/ranking')
def ranking():
    ensure_session()
    count = session.get('comparison_count', 0)

    if count == 0:
        return redirect(url_for('index'))

    # Only show books that have been in at least one comparison
    books = (Book.query
             .filter((Book.wins + Book.losses) > 0)
             .order_by(Book.elo.desc())
             .all())

    total_comparisons = Comparison.query.count()
    total_books = Book.query.count()

    # Books this session has seen
    my_comps = Comparison.query.filter_by(session_id=session['session_id']).all()
    seen_ids = set()
    for c in my_comps:
        seen_ids.add(c.book_a_id)
        seen_ids.add(c.book_b_id)
    seen_books = (Book.query.filter(Book.id.in_(seen_ids)).order_by(Book.elo.desc()).all()
                  if seen_ids else [])

    return render_template('ranking.html',
                           books=books,
                           count=count,
                           total_comparisons=total_comparisons,
                           total_books=total_books,
                           seen_books=seen_books)


@app.route('/export')
def export():
    """Download all comparison data as CSV. Protected by EXPORT_TOKEN."""
    token = os.environ.get('EXPORT_TOKEN', '')
    if not token or request.args.get('token') != token:
        return 'Unauthorized', 401

    comparisons = Comparison.query.order_by(Comparison.created_at).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'comparison_id',
        'book_a_gutenberg_id', 'book_a_title', 'book_a_author',
        'book_a_elo_at_export',
        'book_b_gutenberg_id', 'book_b_title', 'book_b_author',
        'book_b_elo_at_export',
        'winner_gutenberg_id', 'winner_title',
        'session_id', 'created_at',
    ])

    for c in comparisons:
        writer.writerow([
            c.id,
            c.book_a.gutenberg_id, c.book_a.title, c.book_a.author,
            round(c.book_a.elo, 2),
            c.book_b.gutenberg_id, c.book_b.title, c.book_b.author,
            round(c.book_b.elo, 2),
            c.winner.gutenberg_id, c.winner.title,
            c.session_id,
            c.created_at.isoformat() if c.created_at else '',
        ])

    output.seek(0)
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=comparisons.csv'},
    )


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=True, port=port)
