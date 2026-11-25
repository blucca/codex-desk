"""Literal local recall of opened Desk evidence and saved task preparation."""
import json
import math
import os
from pathlib import Path
import time
import unicodedata

from .handoff import visible_text


MAX_ITEM_CHARS = 200_000
SNIPPET_CHARS = 420
VISIBLE_TYPES = frozenset(('userMessage', 'agentMessage', 'commandExecution',
    'fileChange', 'mcpToolCall', 'dynamicToolCall', 'collabAgentToolCall', 'subAgentActivity'))
DELTA_TYPES = {'item/agentMessage/delta': 'agentMessage',
               'item/commandExecution/outputDelta': 'commandExecution'}


def normalize(value):
    return unicodedata.normalize('NFKC', unicodedata.normalize('NFKC', value).casefold())


def canonical_cwd(value):
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 200


def _item_text(item):
    if not isinstance(item, dict) or item.get('type') not in VISIBLE_TYPES:
        return ''
    try:
        return visible_text(item)[:MAX_ITEM_CHARS]
    except (TypeError, ValueError, AttributeError):
        # An unsupported native item shape must not break the activity reader.
        return ''


def _timestamp(value, fallback):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return value / 1000 if value > 100_000_000_000 else value
    return fallback


def _put(store, session, turn_id, item, updated, complete=False):
    if not _identifier(turn_id) or not isinstance(item, dict) or not _identifier(item.get('id')):
        return
    if not complete and _ended(store, session, turn_id):
        return
    text = _item_text(item)
    if not text:
        return
    store.db.execute('''INSERT INTO recall_items
        (session_id,turn_id,item_id,item_type,visible_text,normalized_text,updated,complete)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(session_id,turn_id,item_id) DO UPDATE SET
        item_type=excluded.item_type,visible_text=excluded.visible_text,
        normalized_text=excluded.normalized_text,
        updated=CASE WHEN visible_text=excluded.visible_text THEN updated
                     ELSE max(updated,excluded.updated) END,
        complete=max(complete,excluded.complete)
        WHERE recall_items.complete=0 OR excluded.complete=1''',
        (session, turn_id, item['id'], item['type'], text, normalize(text), updated, int(complete)))


def _ended(store, session, turn_id):
    return store.db.execute('SELECT 1 FROM recall_turns WHERE session_id=? AND turn_id=?',
                            (session, turn_id)).fetchone() is not None


def _turn(store, session, turn, updated, complete=False):
    if not isinstance(turn, dict) or not _identifier(turn.get('id')):
        return
    updated = _timestamp(turn.get('completedAt') or turn.get('startedAt'), updated)
    items = turn.get('items')
    if isinstance(items, list):
        for item in items:
            _put(store, session, turn['id'], item, updated, complete)
    if complete:
        store.db.execute('INSERT OR IGNORE INTO recall_turns VALUES(?,?)', (session, turn['id']))
        store.db.execute('UPDATE recall_items SET complete=1 WHERE session_id=? AND turn_id=?',
                         (session, turn['id']))


def record_event(store, session, event, seq, fallback=None):
    """The same parent-scoped reducer handles live events and legacy backfill."""
    row = store.db.execute('SELECT thread_id,updated FROM sessions WHERE id=?', (session,)).fetchone()
    if row is None or session == 'native-catalog':
        return
    if isinstance(event, dict) and isinstance(event.get('params'), dict) and row[0]:
        params = event['params']
        scope = params.get('threadId')
        if not scope and isinstance(params.get('thread'), dict):
            scope = params['thread'].get('id')
        if not scope or scope == row[0]:
            updated = _timestamp(event.get('emittedAtMs'), fallback if fallback is not None else time.time())
            method = event.get('method')
            if method in ('item/started', 'item/completed') and 'id' not in event:
                _put(store, session, params.get('turnId'), params.get('item'), updated, method == 'item/completed')
            elif method in ('turn/started', 'turn/completed') and 'id' not in event:
                _turn(store, session, params.get('turn'), updated, method == 'turn/completed')
            elif method in DELTA_TYPES and 'id' not in event:
                turn_id, item_id, delta = params.get('turnId'), params.get('itemId'), params.get('delta')
                if (_identifier(turn_id) and _identifier(item_id) and isinstance(delta, str) and delta
                        and not _ended(store, session, turn_id)):
                    current = store.db.execute('''SELECT visible_text,complete,item_type FROM recall_items
                        WHERE session_id=? AND turn_id=? AND item_id=?''', (session, turn_id, item_id)).fetchone()
                    kind = DELTA_TYPES[method]
                    if current is None:
                        _put(store, session, turn_id, {'id': item_id, 'type': kind}, updated)
                        current = store.db.execute('''SELECT visible_text,complete,item_type FROM recall_items
                            WHERE session_id=? AND turn_id=? AND item_id=?''', (session, turn_id, item_id)).fetchone()
                    if current and not current[1] and current[2] == kind:
                        text = (current[0] + delta)[:MAX_ITEM_CHARS]
                        store.db.execute('''UPDATE recall_items SET visible_text=?,normalized_text=?,updated=?
                            WHERE session_id=? AND turn_id=? AND item_id=?''',
                            (text, normalize(text), updated, session, turn_id, item_id))
    store.db.execute('''INSERT INTO recall_checkpoints VALUES(?,?)
        ON CONFLICT(session_id) DO UPDATE SET last_seq=max(last_seq,excluded.last_seq)''', (session, seq))


def initialize(store):
    store.db.create_function('recall_normalize', 1, normalize, deterministic=True)
    store.db.create_function('recall_cwd', 1, canonical_cwd, deterministic=True)
    store.db.executescript('''CREATE TABLE IF NOT EXISTS recall_items(
        session_id TEXT NOT NULL, turn_id TEXT NOT NULL, item_id TEXT NOT NULL,
        item_type TEXT NOT NULL, visible_text TEXT NOT NULL, normalized_text TEXT NOT NULL,
        updated REAL NOT NULL, complete INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(session_id,turn_id,item_id));
        CREATE TABLE IF NOT EXISTS recall_checkpoints(
        session_id TEXT PRIMARY KEY NOT NULL,last_seq INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS recall_turns(
        session_id TEXT NOT NULL,turn_id TEXT NOT NULL,PRIMARY KEY(session_id,turn_id));
        CREATE INDEX IF NOT EXISTS recall_recent ON recall_items(updated DESC,session_id);''')
    cursor = store.db.execute('''SELECT e.seq,e.session_id,e.payload,s.updated FROM events e
        JOIN sessions s ON s.id=e.session_id LEFT JOIN recall_checkpoints c ON c.session_id=e.session_id
        WHERE e.seq>coalesce(c.last_seq,0) ORDER BY e.seq''')
    while rows := cursor.fetchmany(100):
        for seq, session, payload, updated in rows:
            try:
                event = json.loads(payload)
            except (ValueError, TypeError):
                event = {}
            record_event(store, session, event, seq, updated or 0)


def save_snapshot(store, session, thread):
    row = store.db.execute('SELECT thread_id FROM sessions WHERE id=?', (session,)).fetchone()
    if (row is None or session == 'native-catalog' or not isinstance(thread, dict)
            or not row[0] or thread.get('id') != row[0]):
        return
    turns = thread.get('turns')
    if isinstance(turns, list):
        updated = _timestamp(thread.get('updatedAt'), time.time())
        for turn in turns:
            _turn(store, session, turn, updated,
                  isinstance(turn, dict) and turn.get('status') in ('completed', 'failed', 'interrupted'))
    # Native summary/read responses can omit turns/items; never erase known evidence.


def _snippet(text, needle):
    # Keep offsets in original visible text across accents, casefold expansions
    # and compatibility characters, rather than slicing at normalized offsets.
    clusters, starts, ends = [], [], []
    start = 0
    for index in range(1, len(text) + 1):
        continuation = index < len(text) and (unicodedata.combining(text[index])
            or (0x1100 <= ord(text[index]) <= 0x11ff and 0x1100 <= ord(text[index - 1]) <= 0x11ff))
        if continuation:
            continue
        folded = normalize(text[start:index])
        clusters.append(folded)
        starts.extend([start] * len(folded))
        ends.extend([index] * len(folded))
        start = index
    position = ''.join(clusters).find(needle)
    if position < 0:
        # Rare cross-cluster compatibility composition still has a literal hit.
        position = normalize(text).find(needle)
        left = min(max(position, 0), max(len(text) - 1, 0))
        right = min(len(text), left + len(needle))
    else:
        left, right = starts[position], ends[position + len(needle) - 1]
    begin = max(0, left - 80)
    end = min(len(text), max(right, begin + SNIPPET_CHARS))
    if end - begin > SNIPPET_CHARS:
        begin, end = left, min(len(text), left + SNIPPET_CHARS)
    snippet = ('…' if begin else '') + text[begin:end] + ('…' if end < len(text) else '')
    return snippet, text[left:min(right, end)]


def search(store, q, cwd=None, include_archived=False, limit=30):
    if not isinstance(q, str) or not 2 <= len(q.strip()) <= 200:
        raise ValueError('Enter a recall phrase of 2–200 characters')
    q = q.strip()
    try:
        q.encode('utf-8')
    except UnicodeEncodeError:
        raise ValueError('Enter valid Unicode recall text') from None
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Choose a recall limit from 1 to 50')
    if type(include_archived) is not bool:
        raise ValueError('Choose whether to include archived sessions')
    if cwd is not None and (not isinstance(cwd, str) or not cwd.strip()):
        raise ValueError('Choose a project folder')
    scoped = canonical_cwd(cwd) if cwd is not None else None
    needle = normalize(q)
    with store.lock:
        tables = {row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        parts = ["""SELECT session_id,'activity' kind,turn_id,item_id,NULL followup_id,
            visible_text text,normalized_text folded,updated FROM recall_items"""]
        if 'drafts' in tables:
            parts.append("""SELECT session_id,'draft',NULL,NULL,NULL,text,recall_normalize(text),NULL
                FROM drafts WHERE revision>0 AND trim(text)<>''""")
        if 'followups' in tables:
            parts.append("""SELECT session_id,'followup',NULL,NULL,id,text,recall_normalize(text),NULL
                FROM followups""")
        scope = "s.id<>'native-catalog' AND (? OR s.archived=0) AND (? IS NULL OR recall_cwd(s.cwd)=?)"
        options = (int(include_archived), scoped, scoped)
        corpus = ' UNION ALL '.join(parts)
        joined = f'''FROM ({corpus}) r JOIN sessions s ON s.id=r.session_id WHERE {scope}'''
        counts = {kind: count for kind, count in store.db.execute(
            'SELECT kind,count(*) ' + joined + ' GROUP BY kind', options)}
        sessions = store.db.execute('SELECT count(*) FROM sessions s WHERE ' + scope, options).fetchone()[0]
        total = store.db.execute('SELECT count(*) ' + joined + ' AND instr(r.folded,?)>0',
                                 (*options, needle)).fetchone()[0]
        cursor = store.db.execute('''SELECT s.id,s.name,s.cwd,s.profile,s.archived,r.kind,
            r.turn_id,r.item_id,r.followup_id,r.text,coalesce(r.updated,s.updated,0) updated '''
            + joined + ''' AND instr(r.folded,?)>0
            ORDER BY updated DESC,s.id,r.kind,r.turn_id,r.item_id,r.followup_id LIMIT ?''',
            (*options, needle, limit))
        results = []
        for session, name, project, profile, archived, kind, turn, item, followup, text, updated in cursor:
            snippet, match = _snippet(text, needle)
            results.append({'session_id': session, 'session_name': name, 'cwd': canonical_cwd(project),
                'profile': profile, 'archived': bool(archived), 'kind': kind, 'turn_id': turn,
                'item_id': item, 'followup_id': followup, 'snippet': snippet,
                'match_text': match, 'updated': updated})
    return {'query': q, 'cwd': scoped, 'archived': include_archived, 'limit': limit,
        'total': total, 'truncated': total > len(results), 'results': results,
        'coverage': {'text': 'Cached evidence from imported/opened Desk sessions and saved drafts/follow-ups; '
                     'not whole native history. Visible activity is cached up to 200,000 characters per item.',
            'sessions': sessions, 'activity_items': counts.get('activity', 0),
            'drafts': counts.get('draft', 0), 'followups': counts.get('followup', 0)}}
