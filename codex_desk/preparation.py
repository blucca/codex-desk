"""Saved next-task preparation, readable independently of native startup."""

from .drafts import _read as _read_draft
from .followups import _entries, _reservation
from .recall import canonical_cwd


def preparation_snapshot(store, include_archived=False, cwd=None):
    """Group saved drafts and ordered follow-ups in one read-only snapshot.

    Preparation tables are created by explicit saves, not by this overview.
    The read transaction also keeps draft/queue/admission revisions consistent
    when another Store connection is saving into the retained database.
    """
    if type(include_archived) is not bool:
        raise ValueError('Choose whether to include archived sessions')
    if cwd is not None and (not isinstance(cwd, str) or not cwd.strip()):
        raise ValueError('Choose a project folder')
    scoped = canonical_cwd(cwd) if cwd is not None else None
    with store.lock:
        # A savepoint starts a read transaction without taking a write lock or
        # committing an existing caller-owned transaction on this connection.
        store.db.execute('SAVEPOINT prepared_work_snapshot')
        try:
            tables = {row[0] for row in store.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('drafts','followups','followup_reservations')")}
            prepared = []
            if 'drafts' in tables:
                prepared.append("EXISTS (SELECT 1 FROM drafts d WHERE d.session_id=s.id "
                                "AND d.revision>0 AND d.text<>'')")
            if 'followups' in tables:
                prepared.append('EXISTS (SELECT 1 FROM followups f WHERE f.session_id=s.id)')
            if 'followup_reservations' in tables:
                prepared.append('EXISTS (SELECT 1 FROM followup_reservations p WHERE p.session_id=s.id)')
            if not prepared:
                return {'sessions': []}
            cursor = store.db.execute(
                '''SELECT s.id,s.name,s.cwd,s.profile,s.archived,s.status,coalesce(s.updated,0),s.mode
                   FROM sessions s WHERE s.id<>'native-catalog' AND (? OR s.archived=0)
                   AND (? IS NULL OR recall_cwd(s.cwd)=?) AND ('''
                + ' OR '.join(prepared) + ') ORDER BY coalesce(s.updated,0) DESC,s.id',
                (int(include_archived), scoped, scoped))
            sessions = []
            for identifier, name, project, profile, archived, status, updated, mode in cursor:
                draft = _read_draft(store, identifier, mode) if 'drafts' in tables else None
                if draft is not None and (draft['revision'] <= 0 or not draft['text'].strip()):
                    draft = None
                followups = {'entries': _entries(store, identifier) if 'followups' in tables else [],
                             'reservation': _reservation(store, identifier)
                             if 'followup_reservations' in tables else None}
                if draft is None and not followups['entries'] and followups['reservation'] is None:
                    continue
                sessions.append({'id': identifier, 'name': name, 'cwd': canonical_cwd(project),
                                 'profile': profile, 'archived': bool(archived), 'status': status,
                                 'updated': updated, 'draft': draft, 'followups': followups})
            return {'sessions': sessions}
        finally:
            store.db.execute('RELEASE SAVEPOINT prepared_work_snapshot')
