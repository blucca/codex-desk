"""Private, revisioned next-task preparation for an existing Desk session."""

MAX_DRAFT_CHARS = 200_000


class DraftConflict(ValueError):
    """The caller's revision is stale; current is the saved draft to review."""

    def __init__(self, current):
        self.current = dict(current)
        super().__init__(
            "Prepared task changed in another page. Review the current draft before saving again.")


def _session_mode(store, session):
    if not isinstance(session, str) or not session or session == 'native-catalog':
        raise ValueError('Select an existing project session')
    row = store.db.execute('SELECT mode FROM sessions WHERE id=?', (session,)).fetchone()
    if row is None:
        raise ValueError('Session not found')
    return row[0] if row[0] in ('native', 'plan') else 'native'


def _ensure_table(store):
    store.db.execute('''CREATE TABLE IF NOT EXISTS drafts(
        session_id TEXT PRIMARY KEY NOT NULL,
        text TEXT NOT NULL,
        mode TEXT NOT NULL,
        revision INTEGER NOT NULL,
        writer TEXT,
        edit_sequence INTEGER)''')
    columns = {row[1] for row in store.db.execute('PRAGMA table_info(drafts)')}
    for column, definition in (('writer', 'TEXT'), ('edit_sequence', 'INTEGER')):
        if column not in columns:
            store.db.execute(f'ALTER TABLE drafts ADD COLUMN {column} {definition}')


def _read(store, session, initial_mode):
    row = store.db.execute(
        'SELECT text,mode,revision FROM drafts WHERE session_id=?', (session,)).fetchone()
    if row is None:
        return {'text': '', 'mode': initial_mode, 'revision': 0}
    return {'text': row[0], 'mode': row[1], 'revision': row[2]}


def load_draft(store, session):
    """Return a saved draft, or revision zero using the session's last mode."""
    with store.lock, store.db:
        # Schema upgrades are serialized with saves on other Store connections.
        store.db.execute('BEGIN IMMEDIATE')
        initial_mode = _session_mode(store, session)
        _ensure_table(store)
        return _read(store, session, initial_mode)


def save_draft(store, session, text, mode, expected_revision, writer=None, sequence=None):
    """Save by revision; newer same-page edits can recover a delayed save reply."""
    if not isinstance(text, str) or len(text) > MAX_DRAFT_CHARS:
        raise ValueError(f'Prepared task must be text of at most {MAX_DRAFT_CHARS:,} characters')
    if mode not in ('native', 'plan'):
        raise ValueError('Choose Work or Plan mode')
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('Use a nonnegative draft revision')
    identified = writer is not None or sequence is not None
    if identified and (not isinstance(writer, str) or not writer or len(writer) > 128
                       or type(sequence) is not int or not 0 <= sequence <= 2**63 - 1):
        raise ValueError('Use a page writer ID and a nonnegative edit sequence')
    with store.lock, store.db:
        # Start the SQLite write transaction before reading the revision. This
        # also protects against another Store connection to the same state file.
        store.db.execute('BEGIN IMMEDIATE')
        initial_mode = _session_mode(store, session)
        _ensure_table(store)
        current = _read(store, session, initial_mode)
        lineage = store.db.execute(
            'SELECT writer,edit_sequence FROM drafts WHERE session_id=?', (session,)).fetchone()
        same_writer = identified and lineage is not None and lineage[0] == writer
        if same_writer and sequence <= lineage[1]:
            if sequence == lineage[1] and current['text'] == text and current['mode'] == mode:
                # A keepalive or retry of the same committed edit needs no new revision.
                return current
            raise DraftConflict(current)
        same_page_recovery = (same_writer and sequence > lineage[1]
                              and expected_revision < current['revision'])
        if current['revision'] != expected_revision and not same_page_recovery:
            raise DraftConflict(current)
        saved = {'text': text, 'mode': mode, 'revision': current['revision'] + 1}
        store.db.execute('''INSERT INTO drafts(session_id,text,mode,revision,writer,edit_sequence)
            VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
            text=excluded.text,mode=excluded.mode,revision=excluded.revision,
            writer=excluded.writer,edit_sequence=excluded.edit_sequence''',
            (session, saved['text'], saved['mode'], saved['revision'], writer, sequence))
        return saved


def draft_snapshot(store, session):
    """Read an admission's current draft without schema upgrades or writes."""
    with store.lock:
        initial_mode = _session_mode(store, session)
        if store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone() is None:
            return {'text': '', 'mode': initial_mode, 'revision': 0}
        return _read(store, session, initial_mode)


def clear_admitted_draft(store, session, payload):
    """Clear only the captured saved edit; a later edit or writer survives.

    Clearing does not use up a page edit sequence. The next genuine edit from
    that page can save against the returned revision with its next sequence.
    """
    with store.lock, store.db:
        store.db.execute('BEGIN IMMEDIATE')
        initial_mode = _session_mode(store, session)
        _ensure_table(store)
        current = _read(store, session, initial_mode)
        lineage = store.db.execute(
            'SELECT writer,edit_sequence FROM drafts WHERE session_id=?', (session,)).fetchone()
        if (current != {key: payload[key] for key in ('text', 'mode', 'revision')}
                or lineage is None or tuple(lineage) != (payload['writer'], payload['sequence'])):
            return current
        saved = {'text': '', 'mode': current['mode'], 'revision': current['revision'] + 1}
        store.db.execute('UPDATE drafts SET text=?,revision=? WHERE session_id=?',
                         (saved['text'], saved['revision'], session))
        return saved
