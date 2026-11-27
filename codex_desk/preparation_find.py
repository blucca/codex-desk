"""Literal lookup inside existing saved preparation; no parallel index or native read."""
from .preparation import preparation_snapshot
from .recall import canonical_cwd, normalize, _snippet, _read_snapshot
from .turn_records import unresolved_request_query


def lookup_snapshot(store, q=None, include_archived=False, cwd=None, limit=30, offset=0):
    """Keep the existing scoped owners and separately page matching controls.

    Results carry only exact owner/lifecycle identities and a bounded original
    snippet. Selecting a result must reread that existing owner or receipt;
    lookup is neither admission nor permission to overwrite its preparation.
    """
    if q is None:
        return preparation_snapshot(store, include_archived=include_archived, cwd=cwd)
    if not isinstance(q, str) or len(q) > 200 or any(0xD800 <= ord(c) <= 0xDFFF for c in q):
        raise ValueError('Use a remembered phrase of at most 200 Unicode characters')
    q = q.strip()
    if q and len(q) < 2:
        raise ValueError('Use at least two characters to find saved preparation')
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Choose a preparation lookup limit from 1 to 50')
    if type(offset) is not int or not 0 <= offset <= 9_223_372_036_854_775_807:
        raise ValueError('Choose a preparation lookup offset of zero or more')
    needle = normalize(q)
    with _read_snapshot(store):
        snapshot = preparation_snapshot(store, include_archived=include_archived, cwd=cwd)
        rows = snapshot['sessions']
        hits = []
        if needle:
            scoped = canonical_cwd(cwd) if cwd is not None else None
            sql, args = unresolved_request_query(scoped, include_archived)
            requests = {(session, token): (status, mode, text)
                        for session, token, status, mode, text in store.db.execute(sql, args)}

            def add(row, kind, text, **identity):
                if not isinstance(text, str) or needle not in normalize(text):
                    return
                snippet, match = _snippet(text, needle)
                hits.append({'session_id': row['id'], 'kind': kind,
                             'name': row['name'], 'cwd': row['cwd'],
                             'profile': row['profile'], 'archived': row['archived'],
                             'owner_status': row['status'], 'updated': row['updated'],
                             'snippet': snippet, 'match_text': match, **identity})

            for row in rows:
                add(row, 'session', row['name'], control='review')
                draft = row['draft']
                if draft:
                    add(row, 'draft', draft['text'], mode=draft['mode'],
                        revision=draft['revision'], control='draft')
                for entry in row['followups']['entries']:
                    add(row, 'followup', entry['text'], followup_id=entry['id'],
                        mode=entry['mode'], revision=entry['revision'],
                        state=entry['state'], order=entry['order'], control='followup')
                reservation = row['followups']['reservation']
                if reservation:
                    add(row, 'reservation', reservation['text'], token=reservation['token'],
                        followup_id=reservation['entry_id'], revision=reservation['revision'],
                        mode=reservation['mode'], state=reservation['state'], control='reservation')
                request = row.get('turn_request')
                if request:
                    captured = requests.get((row['id'], request['token']))
                    if captured:
                        status, mode, text = captured
                        add(row, 'turn_request', text, token=request['token'],
                            mode=mode, state=status, control='turn_request')
        return {**snapshot, 'lookup': {'q': q, 'limit': limit, 'offset': offset,
                                     'total': len(hits), 'results': hits[offset:offset + limit],
                                     'has_more': offset + limit < len(hits)}}
