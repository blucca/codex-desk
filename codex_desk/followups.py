"""Private prepared follow-ups and explicit, revision-bound admission receipts."""
from contextlib import contextmanager
import uuid


MAX_FOLLOWUP_CHARS = 200_000


class FollowupConflict(ValueError):
    def __init__(self, current):
        self.current = current
        super().__init__('Follow-up preparation changed. Review the current entry or reservation.')


def _identifier(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Select a follow-up entry')


def _revision(value):
    if type(value) is not int or value < 1:
        raise ValueError('Use the entry revision you reviewed')


def _preparation(text, mode):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_FOLLOWUP_CHARS:
        raise ValueError(f'Enter a follow-up task of 1–{MAX_FOLLOWUP_CHARS:,} characters')
    if mode not in ('native', 'plan'):
        raise ValueError('Choose Work or Plan mode')


@contextmanager
def _transaction(store, session):
    with store.lock, store.db:
        store.db.execute('BEGIN IMMEDIATE')
        if not isinstance(session, str) or not session or session == 'native-catalog':
            raise ValueError('Select an existing project session')
        if store.db.execute('SELECT 1 FROM sessions WHERE id=?', (session,)).fetchone() is None:
            raise ValueError('Session not found')
        for statement in ('''CREATE TABLE IF NOT EXISTS followups(
                id TEXT PRIMARY KEY NOT NULL, session_id TEXT NOT NULL,
                text TEXT NOT NULL, mode TEXT NOT NULL, position INTEGER NOT NULL,
                revision INTEGER NOT NULL, state TEXT NOT NULL
                    CHECK(state IN ('queued','reserved','needs_review')))''',
            'CREATE INDEX IF NOT EXISTS followups_order ON followups(session_id,position,id)',
            '''CREATE TABLE IF NOT EXISTS followup_reservations(
                session_id TEXT PRIMARY KEY NOT NULL, token TEXT UNIQUE NOT NULL,
                entry_id TEXT NOT NULL, entry_revision INTEGER NOT NULL,
                text TEXT NOT NULL, mode TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('reserved','unknown')))'''):
            store.db.execute(statement)
        yield


def _as_entry(row):
    return dict(zip(('id', 'text', 'mode', 'order', 'revision', 'state'), row))


def _entries(store, session):
    return [_as_entry(row) for row in store.db.execute(
        'SELECT id,text,mode,position,revision,state FROM followups WHERE session_id=? ORDER BY position,id',
        (session,))]


def _entry(store, session, identifier):
    _identifier(identifier)
    row = store.db.execute(
        'SELECT id,text,mode,position,revision,state FROM followups WHERE session_id=? AND id=?',
        (session, identifier)).fetchone()
    if row is None:
        raise ValueError('Follow-up entry not found in this session')
    return _as_entry(row)


def _reservation(store, session):
    row = store.db.execute(
        'SELECT token,entry_id,entry_revision,text,mode,state FROM followup_reservations WHERE session_id=?',
        (session,)).fetchone()
    if row is None:
        return None
    return {'session_id': session, **dict(zip(
        ('token', 'entry_id', 'revision', 'text', 'mode', 'state'), row))}


def _snapshot(store, session):
    return {'entries': _entries(store, session), 'reservation': _reservation(store, session)}


def _renumber(store, session):
    for position, entry in enumerate(_entries(store, session), 1):
        store.db.execute('UPDATE followups SET position=? WHERE id=?', (position, entry['id']))


def _ids(values):
    if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
        raise ValueError('Use a list of follow-up entry IDs')
    if len(values) != len(set(values)):
        raise ValueError('Each follow-up entry must occur once')


def _expected_order(store, session, expected_order):
    if expected_order is not None:
        _ids(expected_order)
        if expected_order != [entry['id'] for entry in _entries(store, session)]:
            raise FollowupConflict(_snapshot(store, session))


def list_followups(store, session):
    """Return preparation order/state; this never sends or releases a reservation."""
    with _transaction(store, session):
        return _entries(store, session)


def followup_snapshot(store, session):
    """Read entries and their admission receipt in one SQLite snapshot."""
    with _transaction(store, session):
        return _snapshot(store, session)


def add_followup(store, session, text, mode='native'):
    _preparation(text, mode)
    with _transaction(store, session):
        position = store.db.execute(
            'SELECT coalesce(max(position),0)+1 FROM followups WHERE session_id=?', (session,)).fetchone()[0]
        identifier = uuid.uuid4().hex
        store.db.execute('INSERT INTO followups VALUES(?,?,?,?,?,?,?)',
                         (identifier, session, text, mode, position, 1, 'queued'))
        return _entry(store, session, identifier)


def edit_followup(store, session, identifier, text, mode, expected_revision):
    """Every deliberate edit advances preparation revision, even identical text."""
    _preparation(text, mode)
    _revision(expected_revision)
    with _transaction(store, session):
        current = _entry(store, session, identifier)
        if current['revision'] != expected_revision:
            raise FollowupConflict({'entry': current, 'reservation': _reservation(store, session)})
        store.db.execute('UPDATE followups SET text=?,mode=?,revision=revision+1 WHERE id=?',
                         (text, mode, identifier))
        return _entry(store, session, identifier)


def remove_followup(store, session, identifier, expected_revision):
    _revision(expected_revision)
    with _transaction(store, session):
        current = _entry(store, session, identifier)
        if current['revision'] != expected_revision:
            raise FollowupConflict({'entry': current, 'reservation': _reservation(store, session)})
        if current['state'] != 'queued':
            raise ValueError('Review the pending admission receipt before removing this preparation')
        store.db.execute('DELETE FROM followups WHERE id=?', (identifier,))
        _renumber(store, session)
        return {'removed': identifier}


def reorder_followups(store, session, identifiers, expected_order=None):
    """Move reviewed preparations; an already reserved entry keeps its position."""
    _ids(identifiers)
    with _transaction(store, session):
        _expected_order(store, session, expected_order)
        entries = _entries(store, session)
        if set(identifiers) != {entry['id'] for entry in entries}:
            raise ValueError('Include every follow-up in this session exactly once')
        current = {entry['id']: entry for entry in entries}
        for position, identifier in enumerate(identifiers, 1):
            entry = current[identifier]
            if entry['state'] != 'queued' and entry['order'] != position:
                raise ValueError('A pending admission keeps its position until reviewed')
        for position, identifier in enumerate(identifiers, 1):
            if current[identifier]['order'] != position:
                store.db.execute('UPDATE followups SET position=?,revision=revision+1 WHERE id=?',
                                 (position, identifier))
        return _entries(store, session)


def clear_followups(store, session, expected_order=None):
    """Clear queued preparation only; an unresolved admission remains reviewable."""
    with _transaction(store, session):
        _expected_order(store, session, expected_order)
        removed = [entry['id'] for entry in _entries(store, session) if entry['state'] == 'queued']
        store.db.execute("DELETE FROM followups WHERE session_id=? AND state='queued'", (session,))
        _renumber(store, session)
        return {'removed': removed, 'entries': _entries(store, session),
                'reservation': _reservation(store, session)}


def pending_followup(store, session):
    """Return an unconfirmed receipt snapshot, including after Store reopen."""
    with _transaction(store, session):
        return _reservation(store, session)


def reserve_followup(store, session, identifier=None, expected_revision=None, *, first_only=False):
    """Explicitly capture one next entry; None means empty or already awaiting review.

    Passing an entry ID requires its reviewed revision. Omitting both selects
    the current first queued entry. Native turn admission remains the caller's job.
    """
    if (identifier is None) != (expected_revision is None):
        raise ValueError('Select both the entry ID and its reviewed revision')
    if identifier is not None:
        _identifier(identifier)
        _revision(expected_revision)
    with _transaction(store, session):
        if _reservation(store, session) is not None:
            return None
        if identifier is None:
            entries = [entry for entry in _entries(store, session) if entry['state'] == 'queued']
            if not entries:
                return None
            current = entries[0]
        else:
            current = _entry(store, session, identifier)
            if current['revision'] != expected_revision:
                raise FollowupConflict({'entry': current, 'reservation': None})
            if current['state'] != 'queued':
                raise ValueError('Review this entry before reserving it again')
        if first_only and current['id'] != _entries(store, session)[0]['id']:
            raise FollowupConflict(_snapshot(store, session))
        token = uuid.uuid4().hex
        store.db.execute("UPDATE followups SET state='reserved' WHERE id=?", (current['id'],))
        store.db.execute('INSERT INTO followup_reservations VALUES(?,?,?,?,?,?,?)',
                         (session, token, current['id'], current['revision'],
                          current['text'], current['mode'], 'reserved'))
        return _reservation(store, session)


def record_followup_receipt(store, session, token, identifier, expected_revision, outcome):
    """Resolve the exact captured version; unknown keeps a blocker for explicit review."""
    _identifier(token)
    _identifier(identifier)
    _revision(expected_revision)
    if outcome not in ('accepted', 'rejected', 'unknown'):
        raise ValueError('Record accepted, rejected or unknown admission')
    with _transaction(store, session):
        reservation = _reservation(store, session)
        if (reservation is None or reservation['token'] != token
                or reservation['entry_id'] != identifier or reservation['revision'] != expected_revision):
            raise FollowupConflict(_snapshot(store, session))
        current = _entry(store, session, identifier)
        if outcome == 'unknown':
            store.db.execute("UPDATE followups SET state='needs_review' WHERE id=?", (identifier,))
            store.db.execute("UPDATE followup_reservations SET state='unknown' WHERE session_id=?", (session,))
            return {'outcome': outcome, 'consumed': False, 'entry': _entry(store, session, identifier),
                    'reservation': _reservation(store, session)}
        consumed = outcome == 'accepted' and current['revision'] == expected_revision
        if consumed:
            store.db.execute('DELETE FROM followups WHERE id=?', (identifier,))
        else:
            store.db.execute("UPDATE followups SET state='queued' WHERE id=?", (identifier,))
        store.db.execute('DELETE FROM followup_reservations WHERE session_id=?', (session,))
        _renumber(store, session)
        return {'outcome': outcome, 'consumed': consumed,
                'entry': None if consumed else _entry(store, session, identifier), 'reservation': None}
