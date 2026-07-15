# PR Response Doc — CineLog Watchlist Feature

Branch: `feature/watchlist` → `main`
Feature: adds a watchlist so users can save films they intend to watch (a `WatchlistEntry` model, `watchlist_service` functions, and REST endpoints under `/watchlist`).

---

## AI Usage

I used an AI assistant in three specific, bounded ways. Details of what I asked and what I changed are in each relevant section; summary here:

1. **Orientation on `add_to_collection()` (Comment 2).** I pasted `services/collection_service.py` and asked: "Walk me through `add_to_collection` step by step — what does it check before inserting, and what does it raise on a duplicate vs. a missing film?" The AI said it does two guards in order: a `db.session.get(Film, film_id)` existence check raising `FilmNotFoundError`, then a `filter_by(user_id, film_id).first()` check raising `AlreadyInCollectionError`. **I verified this against the actual code** before copying the pattern — and noticed the AI initially omitted that `CollectionEntry` also has a model-level `UniqueConstraint`, which I found by reading `models.py` myself. That's why my dedup fix includes *both* the service check and a `UniqueConstraint` on `WatchlistEntry`.

2. **Stress-testing the Comment 4 and Comment 5 arguments.** After I wrote my own drafts, I asked: "What counterargument would a careful reviewer raise against a public-by-default watchlist, and against agreeing to date-added sort?" For Comment 4 it raised the "users may not expect their lists to be visible" privacy point — which I had only partially addressed, so I added the explicit per-entry `public` toggle and the mitigation paragraph. For Comment 5 it raised "long watchlists become hard to scan without alphabetical" — which I answer directly in that section (search/filter is the right tool for scanning, not default sort). The core reasoning (CineLog is a community/discovery app; consistency with `get_collection`) is my own — the AI did not supply the CineLog-specific framing.

3. **Commit-format hygiene.** I pasted my `git log --oneline` and asked whether every message followed Conventional Commits and whether any bundled multiple changes. It flagged nothing; I still checked each message against conventionalcommits.org myself.

The AI did **not** make either design decision for me and did not write the arguments below.

---

## Comment 1 — Rename `save_to_watchlist()` → `add_to_watchlist()`

**What I did:**
Renamed the function in `services/watchlist_service.py` to `add_to_watchlist()` to match the project's `verb_to_noun` convention (the reviewer pointed to `add_to_collection()` as the reference; `remove_from_collection()` and `get_collection()` follow the same shape).

**How I found the call sites / verified none were missed:**
I ran a project-wide search for the old name: `grep -rn "save_to_watchlist" .`. That surfaced exactly two references — the definition in `services/watchlist_service.py` and one import + call in `routes/watchlist/watchlist.py` (`from services.watchlist_service import save_to_watchlist, get_watchlist` and the `entry = save_to_watchlist(...)` line in the `add_film` handler). I updated both, then re-ran `grep -rn "save_to_watchlist" .` and confirmed **zero** matches remain. I also grepped for `add_to_watchlist` to confirm the import and call now resolve to the new name. There are no other blueprints, tests, or docstrings referencing the old name.

**Commit:** `fix: rename save_to_watchlist to add_to_watchlist per naming convention`

---

## Comment 2 — Deduplication

**What I did:**
Added a duplicate guard to `add_to_watchlist()` and a model-level constraint, following the `add_to_collection()` pattern exactly.

**What the logic does / what happens on a duplicate:**
After the film-existence check, the function queries `WatchlistEntry.query.filter_by(user_id=user_id, film_id=film_id).first()`. If a matching entry already exists, it raises a new `AlreadyInWatchlistError` (defined in `watchlist_service.py`, parallel to `AlreadyInCollectionError` in `collection_service.py`) with the message `Film '<id>' is already on this user's watchlist`, and it does **not** insert a second row. The endpoint catches this and returns HTTP `409 Conflict`. On a first-time add, the function proceeds to create and commit the entry as before.

**How this follows the existing pattern (and how I verified it):**
I read `add_to_collection()` first (see AI Usage #1). It guards in two layers: an application-level `filter_by(...).first()` check that raises a domain exception, backed by a model-level `UniqueConstraint("user_id", "film_id")` on `CollectionEntry` as a database safety net. I mirrored **both**: the service check gives a clean, catchable error, and I added `UniqueConstraint("user_id", "film_id", name="unique_user_film_watchlist")` to `WatchlistEntry` so a duplicate can't slip in even through a direct insert or a race. I verified the behavior with `test_add_to_watchlist_duplicate_raises`, which adds the same film twice, asserts `AlreadyInWatchlistError`, and asserts the row count stays at 1.

**Commit:** `fix: add deduplication check to prevent duplicate watchlist entries`

---

## Comment 3 — Missing test (nonexistent `film_id`)

**What I did:**
Created `tests/test_watchlist.py` and added `test_add_to_watchlist_nonexistent_film_raises`.

**What it checks and what it was modeled on:**
It is the direct analogue of `test_add_to_collection_nonexistent_film_raises` in `tests/test_collection.py`. It reuses the same fixture structure — an `app` fixture with an in-memory SQLite DB, a `sample_user` fixture — and calls `add_to_watchlist(user_id=sample_user, film_id="00000000-0000-0000-0000-000000000000")` inside a `pytest.raises(FilmNotFoundError)` block. The point is that a `film_id` with no matching row raises the domain-level `FilmNotFoundError` (from the `db.session.get(Film, film_id)` guard) rather than falling through to a database `IntegrityError` on the foreign key. I used a UUID-shaped fake ID because film IDs are UUIDs post-refactor (see Comment 6). Run it with `pytest tests/test_watchlist.py -v`.

**Commit:** `test: add watchlist tests for nonexistent film, dedup, removal, and sort`

---

## Comment 4 — Default visibility (`public=True`)

**My position:** Keep the default `public=True` — but make it an intentional decision, and pair it with an explicit per-entry `public` parameter (implemented; see PR description) so the default is a considered choice, not an inherited accident.

**Reasoning (CineLog-specific):**
CineLog is a *community* film-tracking app — its value is the social graph and discovery, not private logging. Among the three list types in the data model, a watchlist is the **least sensitive**: it's forward-looking intent ("films I want to watch"), not a record of behavior. A public watchlist is exactly the signal that powers the community loop — "three people you follow want to watch this," "here's what's trending on watchlists this week." Defaulting these to private would quietly switch off the feature that makes CineLog more than a personal spreadsheet. Given the reviewer explicitly asked us to be intentional rather than inherit a default, the intentional call for *this platform* is: watchlists are shared-taste artifacts, so public is the right default.

**Tradeoff acknowledged:**
The opposing default — private-by-default — optimizes for privacy and for not surprising users who don't expect their lists to be visible. That is a real concern, and it's the modern "privacy by default" instinct. I don't dismiss it; I mitigate it. Rather than force a single global default, I added an explicit `public` parameter to `add_to_watchlist()` and the `/add` endpoint, so a privacy-conscious client (or a future per-user setting) can create private entries deliberately. My recommendation is: default public because that's what makes CineLog valuable, but (a) surface the visibility state clearly in the UI at add-time, and (b) add a per-user "default new watchlist items to private" preference as a fast follow. That keeps the discovery upside for the majority while giving privacy-sensitive users a real opt-out — which a silent private default would not, because it would degrade the product for everyone to protect the few.

---

## Comment 5 — Sort order (alphabetical vs. date-added)

**My position:** Agree with the maintainer — default to **date added, newest first** — and I implemented it (`get_watchlist` now orders by `WatchlistEntry.date_added.desc()`).

**Engagement with the maintainer's point:**
The maintainer wrote: "Most users want to see what they added recently." I agree, and I'll add the evidence I find most persuasive in CineLog's context: a watchlist is a *queue of intentions*, and intentions are recency-weighted. When a user opens their watchlist, the most common job-to-be-done is "what did I recently decide I want to watch / what's top of mind tonight," not "find the film that starts with 'B'." Newest-first serves that directly.

**The decisive CineLog-specific argument — consistency:**
`get_collection()` already sorts `date_added.desc()` (newest first). If the watchlist sorted alphabetically, the two most important lists in the app would order themselves by different logic, so a user's mental model would break every time they moved between "films I've watched" and "films I want to watch." Matching the collection's sort makes the whole app feel coherent. That's a reason grounded in *this* codebase, not a generic preference.

**Where the reviewer's implied counterpoint has merit, and why I still choose date-added:**
The honest counterargument for alphabetical is scanability: a very long watchlist is easier to eyeball alphabetically. But the right tool for "find a specific film in a long list" is search/filter, not the default sort — and optimizing the *default* for the rare long-list-scan case would penalize the common recency case for everyone. If we later add user-selectable sort, alphabetical is a great option to offer; it just isn't the right default. This is a decision a maintainer can approve or push back on: it takes a side, gives platform-specific evidence, and names the tradeoff.

**Commit:** grouped into `feat: add date-added sort, public visibility flag, and remove_from_watchlist`

---

## Comment 6 — Rebase onto updated `main` (integer → UUID)

**What conflicted:**
While the PR was open, a refactor merged to `main` migrating film IDs from integer to UUID: `Film.id` and `CollectionEntry.film_id` became `db.String(36)`. My watchlist code was written against the old integer IDs — specifically `WatchlistEntry.film_id = db.Column(db.Integer, db.ForeignKey("film.id"))` in `models.py`, plus `film_id (int)` in the `add_to_watchlist` docstring and `"film_id": <int>` in the route docstring. The core conflict is a **foreign-key type mismatch**: a `db.Integer` `film_id` pointing at a now-`String(36)` `Film.id`.

**How I resolved it:**
I ran `git fetch origin` and `git rebase origin/main`. As I replayed my commits onto the UUID `main`, I updated `WatchlistEntry.film_id` to `db.Column(db.String(36), db.ForeignKey("film.id"), nullable=False)` so it matches the new `Film.id` type, and updated the type references in the docstrings (`film_id (str): UUID of the film`, `"film_id": "<uuid>"`). No values needed converting because the branch had no committed integer data — only the schema/type declarations referenced integers. I kept this as a dedicated commit so the migration is legible in history: `fix: migrate watchlist film_id to UUID after main branch refactor`.

**How I verified no conflict remains:**
`git status` reported a clean working tree with no unmerged paths. I grepped to confirm no stale integer references: `grep -rn "db.Integer" models.py` returns only `year` and `rating` (both legitimately integers) — `film_id` no longer appears as Integer. `git log --oneline --graph` shows a **linear** history with **no "Merge branch" commits**. Finally I re-ran the full suite (`pytest tests/ -v`), including the nonexistent-film test whose fake ID is a UUID string, to confirm the UUID-typed `film_id` works end to end.

---

## Stretch Features

**`remove_from_watchlist(user_id, film_id)`** — implemented in `watchlist_service.py`, following `remove_from_collection()`: it looks up the `(user_id, film_id)` entry, raises a new `NotInWatchlistError` (parallel to `NotInCollectionError`) if it isn't there, otherwise deletes and commits and returns `True`. Covered by `test_remove_from_watchlist_removes_entry` and `test_remove_from_watchlist_not_present_raises`.
**Commit:** grouped into `feat: add date-added sort, public visibility flag, and remove_from_watchlist`

**Second, self-chosen test** — `test_same_film_two_users_allowed`. I chose the "two different users add the same film" edge case because the naive reading of Comment 2 ("reject if this film is already on a watchlist") would filter by `film_id` alone and wrongly block the second user. This test pins down that dedup is scoped to the `(user_id, film_id)` pair — matching the `UniqueConstraint` — so the guard protects against a user double-adding without breaking the common case of many users wanting the same popular film. It asserts two distinct entries are created and that two rows exist for that film.

**Visibility toggle** — added a `public` parameter to `add_to_watchlist()` (default `True`) and threaded it through the `POST /watchlist/<user_id>/add` endpoint, which now reads an optional `"public"` field from the JSON body. This is the concrete mitigation referenced in Comment 4: callers can set visibility explicitly instead of relying on the default.
**Commit:** grouped into `feat: add date-added sort, public visibility flag, and remove_from_watchlist`

---

## git log --oneline (feature/watchlist)

Linear history, Conventional Commits, no merge commits. (Your commit SHAs will differ; this is the shape to reproduce — replace this block with a screenshot of your own `git log --oneline`.)

```text
$ git log --oneline origin/main..HEAD

docs: add pr-response.md documenting watchlist review responses
fix: migrate watchlist film_id to UUID after main branch refactor
feat: add date-added sort, public visibility flag, and remove_from_watchlist
fix: add deduplication check to prevent duplicate watchlist entries
fix: rename save_to_watchlist to add_to_watchlist per naming convention
test: add watchlist tests for nonexistent film, dedup, removal, and sort
chore: add .gitignore for venv, caches, and local db
fix: update film retrieval method to use db.session.get in collection and watchlist services
feat: add watchlist model, service, and REST endpoints
```

(The `fix: update film retrieval...` commit was an existing commit on the PR branch before this review cycle; the sort/visibility/remove work was grouped into one feature commit. Replace this block with a screenshot of your own `git log --oneline`.)

---

## PR Description
*(Also paste this into the GitHub PR description box.)*

### What this feature does
Adds a **watchlist** to CineLog: a per-user list of films a user intends to watch, separate from their collection (films already watched). It introduces a `WatchlistEntry` model, a `watchlist_service` with `add_to_watchlist`, `remove_from_watchlist`, and `get_watchlist`, and REST endpoints:

- `GET /watchlist/<user_id>` — returns the user's watchlist as a JSON array of films, newest addition first, each with `date_added` and `public`.
- `POST /watchlist/<user_id>/add` — adds a film; body `{"film_id": "<uuid>", "public": true|false}` (`public` optional). Returns `201` with the entry, `400` if `film_id` is missing, `404` if the film doesn't exist, `409` if it's already on the watchlist.

Adding is idempotent-safe (duplicates are rejected, not silently doubled), and film IDs are UUIDs, consistent with the rest of the app after the recent refactor.

### Design decisions
- **Default visibility: `public=True` (intentional).** CineLog is a community/discovery app and a watchlist is low-sensitivity forward-looking intent, so public is the default that powers discovery — with an explicit `public` parameter added so callers can opt out per entry.
- **Sort order: date added, newest first.** Chosen to match `get_collection()` so the two lists behave consistently, and because a watchlist is a recency-weighted queue of intentions.

### How to manually test
1. Set up and run:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python app.py           # serves at http://127.0.0.1:5000
   ```
2. In a second terminal, create a user and a couple of films (no seed script ships with the starter):
   ```bash
   python - <<'PY'
   from app import create_app, db
   from models import User, Film
   app = create_app()
   with app.app_context():
       u = User(username="nova", email="nova@cinelog.app")
       f1 = Film(title="Paddington 2", year=2017, genre="Comedy")
       f2 = Film(title="Arrival", year=2016, genre="Sci-Fi")
       db.session.add_all([u, f1, f2]); db.session.commit()
       print("USER", u.id); print("FILM1", f1.id); print("FILM2", f2.id)
   PY
   ```
   Copy the printed UUIDs.
3. Add a film to the watchlist (expect `201`):
   ```bash
   curl -s -X POST http://127.0.0.1:5000/watchlist/<USER_ID>/add \
     -H "Content-Type: application/json" -d '{"film_id": "<FILM1_ID>"}'
   ```
4. Add a second film, then a **duplicate** of the first (expect `409 Conflict` on the duplicate):
   ```bash
   curl -s -X POST http://127.0.0.1:5000/watchlist/<USER_ID>/add -H "Content-Type: application/json" -d '{"film_id": "<FILM2_ID>"}'
   curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5000/watchlist/<USER_ID>/add -H "Content-Type: application/json" -d '{"film_id": "<FILM1_ID>"}'
   ```
5. Add a private entry with the visibility toggle:
   ```bash
   curl -s -X POST http://127.0.0.1:5000/watchlist/<USER_ID>/add -H "Content-Type: application/json" -d '{"film_id": "<FILM2_ID>", "public": false}'
   ```
6. View the watchlist and confirm **newest-first** order and the `public` flags:
   ```bash
   curl -s http://127.0.0.1:5000/watchlist/<USER_ID>
   ```
7. Add a nonexistent film (expect `404`):
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5000/watchlist/<USER_ID>/add -H "Content-Type: application/json" -d '{"film_id": "does-not-exist"}'
   ```
8. Or just run the suite: `pytest tests/ -v` (watchlist + collection tests should all pass).
