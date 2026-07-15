"""
services/watchlist_service.py — CineLog

Business logic for the watchlist feature.
"""

from app import db
from models import Film, WatchlistEntry
from services.collection_service import FilmNotFoundError


class AlreadyInWatchlistError(Exception):
    """Raised when a film is already on the user's watchlist."""
    pass


class NotInWatchlistError(Exception):
    """Raised when trying to remove a film that isn't on the watchlist."""
    pass


def add_to_watchlist(user_id, film_id, public=True):
    film = db.session.get(Film, film_id)
    if film is None:
        raise FilmNotFoundError(f"No film found with id '{film_id}'")

    # Deduplication — mirrors the check in add_to_collection().
    existing = WatchlistEntry.query.filter_by(
        user_id=user_id, film_id=film_id
    ).first()
    if existing:
        raise AlreadyInWatchlistError(
            f"Film '{film_id}' is already on this user's watchlist"
        )

    entry = WatchlistEntry(user_id=user_id, film_id=film_id, public=public)
    db.session.add(entry)
    db.session.commit()
    return entry


def remove_from_watchlist(user_id, film_id):
    entry = WatchlistEntry.query.filter_by(
        user_id=user_id, film_id=film_id
    ).first()
    if entry is None:
        raise NotInWatchlistError(
            f"Film '{film_id}' is not on this user's watchlist"
        )
    db.session.delete(entry)
    db.session.commit()
    return True


def get_watchlist(user_id):
    entries = (
        WatchlistEntry.query
        .filter_by(user_id=user_id)
        .order_by(WatchlistEntry.date_added.desc())
        .all()
    )
    result = []
    for entry in entries:
        film = db.session.get(Film, entry.film_id)
        film_dict = film.to_dict()
        film_dict["date_added"] = entry.date_added.isoformat()
        film_dict["public"] = entry.public
        result.append(film_dict)
    return result
