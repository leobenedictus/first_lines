from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Book(db.Model):
    __tablename__ = 'book'

    id = db.Column(db.Integer, primary_key=True)
    gutenberg_id = db.Column(db.Integer, unique=True, nullable=False)
    title = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(300), nullable=False)
    first_sentence = db.Column(db.Text, nullable=False)
    manually_set = db.Column(db.Boolean, default=False)
    elo = db.Column(db.Float, default=1000.0)
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)

    @property
    def comparisons(self):
        return self.wins + self.losses

    def __repr__(self):
        return f'<Book {self.gutenberg_id}: {self.title}>'


class Comparison(db.Model):
    __tablename__ = 'comparison'

    id = db.Column(db.Integer, primary_key=True)
    book_a_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    book_b_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    winner_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    session_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    book_a = db.relationship('Book', foreign_keys=[book_a_id])
    book_b = db.relationship('Book', foreign_keys=[book_b_id])
    winner = db.relationship('Book', foreign_keys=[winner_id])
