"""Last parent native turn, projected from retained events and native reads."""
import json


SNAPSHOT_METHOD = 'desk/nativeTaskSnapshot'
TERMINAL = frozenset(('completed', 'failed', 'interrupted'))
_METHOD = "CASE WHEN json_valid(payload) THEN json_extract(payload,'$.method') END"
_METHODS = _METHOD + " IN ('turn/started','turn/completed','desk/nativeTaskSnapshot')"


def initialize(store):
    store.db.execute('CREATE INDEX IF NOT EXISTS native_outcome_events '
                     'ON events(seq,session_id) WHERE ' + _METHODS)


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 200


def _turn(value):
    if not isinstance(value, dict) or not _identifier(value.get('id')):
        return None
    status = value.get('status')
    error = value.get('error')
    return {'id': value['id'], 'status': status if isinstance(status, str) and status else 'unreported',
            'error': {key: error[key] for key in ('message', 'codexErrorInfo', 'additionalDetails')
                      if key in error} if isinstance(error, dict) and error else None}


def record_snapshot(store, session, thread):
    """Retains a Desk native-history read as compact, source-labeled turn data.

    The caller's Store transaction owns its commit and recall checkpoint.
    """
    binding = store.db.execute('SELECT thread_id FROM sessions WHERE id=?', (session,)).fetchone()
    if (session == 'native-catalog' or not binding or not isinstance(thread, dict)
            or thread.get('id') != binding[0] or not isinstance(thread.get('turns'), list)):
        return None
    turns = [turn for value in thread['turns'] if (turn := _turn(value)) is not None]
    if not turns:
        return None
    event = {'method': SNAPSHOT_METHOD, 'params': {'threadId': binding[0], 'turn': turns[-1],
             'turnIds': [turn['id'] for turn in turns]}}
    payload = json.dumps(event)
    previous = store.db.execute('SELECT payload FROM events WHERE session_id=? AND '
        + _METHODS + ' AND ' + _METHOD + '=? ORDER BY seq DESC LIMIT 1',
        (session, SNAPSHOT_METHOD)).fetchone()
    if previous and previous[0] == payload:
        return None
    cursor = store.db.execute('INSERT INTO events(session_id,payload) VALUES(?,?)', (session, payload))
    return cursor.lastrowid, event


def outcomes(store, sessions):
    """Projects native turn data independently of local readiness."""
    bindings = {row['id']: row['thread_id'] for row in sessions if row.get('thread_id')}
    latest, retired = {}, {}
    with store.lock:
        # Select only outcome fields, not accumulated message/tool bodies.
        rows = store.db.execute('''SELECT session_id,
            json_extract(payload,'$.method'),
            coalesce(json_extract(payload,'$.params.threadId'),
                json_extract(payload,'$.params.thread.id'),json_extract(payload,'$.params.turn.threadId')),
            json_extract(payload,'$.params.turn.id'),
            json_extract(payload,'$.params.turn.status'),
            json_extract(payload,'$.params.turn.error'),
            json_extract(payload,'$.params.turnIds')
            FROM events WHERE ''' + _METHODS + ' ORDER BY seq')
        for session, method, thread, turn, status, error, known in rows:
            bound = bindings.get(session)
            if not bound or (thread and thread != bound) or not _identifier(turn):
                continue
            old = latest.get(session)
            ended = retired.setdefault(session, set())
            if method == SNAPSHOT_METHOD:
                known = json.loads(known) if known else []
                if old and old['turn_id'] != turn and (old['turn_id'] not in known or turn in ended):
                    continue
                if old and old['turn_id'] == turn and old['status'] in TERMINAL:
                    continue
                origin = 'native history read'
            elif method == 'turn/started':
                if turn in ended:
                    continue
                status, error, origin = 'inProgress', None, 'native turn notification'
            else:
                if old and old['turn_id'] != turn:
                    continue
                origin = 'native turn notification'
            if old and old['turn_id'] != turn:
                ended.add(old['turn_id'])
            if status in TERMINAL:
                ended.add(turn)
            latest[session] = {'thread_id': bound, 'turn_id': turn,
                'status': status if isinstance(status, str) and status else 'unreported',
                'error': json.loads(error) if isinstance(error, str) else error, 'source': origin}
    return latest
