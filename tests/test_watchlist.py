"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. Modeled on tests/test_collection.py — same
fixture structure (app / sample_user / sample_film) and same assertion style.
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.watchlist_service import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
    AlreadyInWatchlistError,
    NotInWatchlistError,
)
from services.collection_service import FilmNotFoundError


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add ───────────────────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """Adding a valid film should create a WatchlistEntry in the database."""
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film
        assert entry.public is True  # default visibility

        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


# ── Nonexistent film (Comment 3 — the required test) ─────────────────────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.

    Modeled directly on test_add_to_collection_nonexistent_film_raises.
    """
    with app.app_context():
        fake_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=fake_film_id)


# ── Deduplication (Comment 2) ────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyInWatchlistError,
    not silently create a duplicate entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Stretch: second, self-chosen edge case ───────────────────────────────────

def test_same_film_two_users_allowed(app, sample_film):
    """
    Deduplication is scoped to (user_id, film_id), not global. Two different
    users must each be able to add the SAME film to their own watchlist.

    Chosen because the naive fix for Comment 2 ("reject if any entry exists for
    this film") would wrongly block a second user — this guards against that.
    """
    with app.app_context():
        u1 = User(username="alice", email="alice@example.com")
        u2 = User(username="bob", email="bob@example.com")
        db.session.add_all([u1, u2])
        db.session.commit()

        e1 = add_to_watchlist(user_id=u1.id, film_id=sample_film)
        e2 = add_to_watchlist(user_id=u2.id, film_id=sample_film)

        assert e1.id != e2.id
        assert WatchlistEntry.query.filter_by(film_id=sample_film).count() == 2


# ── Stretch: remove_from_watchlist ───────────────────────────────────────────

def test_remove_from_watchlist_removes_entry(app, sample_user, sample_film):
    """remove_from_watchlist should delete an existing entry and return True."""
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        result = remove_from_watchlist(user_id=sample_user, film_id=sample_film)

        assert result is True
        assert WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first() is None


def test_remove_from_watchlist_not_present_raises(app, sample_user, sample_film):
    """
    Removing a film that isn't on the watchlist should raise
    NotInWatchlistError — mirrors remove_from_collection's NotInCollectionError.
    """
    with app.app_context():
        with pytest.raises(NotInWatchlistError):
            remove_from_watchlist(user_id=sample_user, film_id=sample_film)


# ── Sort order (Comment 5 — date added, newest first) ────────────────────────

def test_get_watchlist_returns_newest_first(app, sample_user):
    """get_watchlist() should return films sorted by date_added descending."""
    with app.app_context():
        from datetime import datetime, timezone, timedelta

        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_b = Film(title="Blade Runner", year=1982, genre="Sci-Fi")
        db.session.add_all([film_a, film_b])
        db.session.commit()

        earlier = datetime.now(timezone.utc) - timedelta(days=5)
        later = datetime.now(timezone.utc)

        db.session.add_all([
            WatchlistEntry(user_id=sample_user, film_id=film_a.id, date_added=earlier),
            WatchlistEntry(user_id=sample_user, film_id=film_b.id, date_added=later),
        ])
        db.session.commit()

        titles = [f["title"] for f in get_watchlist(sample_user)]
        assert titles == ["Blade Runner", "Alien"]  # newest first, not alphabetical
