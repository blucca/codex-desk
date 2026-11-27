"""Literal local recall of opened Desk evidence and saved task preparation."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata

from .handoff import visible_text
from .turn_records import unresolved_request_query


MAX_ITEM_CHARS = 200_000
SNIPPET_CHARS = 420
VISIBLE_TYPES = frozenset(('userMessage', 'agentMessage', 'plan', 'commandExecution',
    'fileChange', 'mcpToolCall', 'dynamicToolCall', 'collabAgentToolCall', 'subAgentActivity'))
DELTA_TYPES = {'item/agentMessage/delta': 'agentMessage',
               'item/plan/delta': 'plan',
               'item/commandExecution/outputDelta': 'commandExecution'}
_ASCII_RUN = re.compile(r'[\x00-\x7f]+')


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
    def recall_cwd(value):
        cache = getattr(store, '_recall_cwds', None)
        if cache is None:
            return canonical_cwd(value)
        if value not in cache:
            cache[value] = canonical_cwd(value)
        return cache[value]
    store.db.create_function('recall_cwd', 1, recall_cwd, deterministic=True)
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


def _folded_chunks(text):
    start = 0
    while start < len(text):
        ascii_run = _ASCII_RUN.match(text, start)
        if ascii_run:
            end = ascii_run.end()
            # A following combining mark belongs with the last ASCII base.
            if end < len(text) and unicodedata.combining(text[end]):
                end -= 1
            if end > start:
                yield text[start:end].casefold(), start, end, True
                start = end
                continue
        end = start + 1
        while end < len(text) and (unicodedata.combining(text[end])
                or (0x1100 <= ord(text[end]) <= 0x11ff and 0x1100 <= ord(text[end - 1]) <= 0x11ff)):
            end += 1
        yield normalize(text[start:end]), start, end, False
        start = end


def _snippet(text, needle):
    # ASCII normalization only changes case, so folded offsets stay exact.
    if text.isascii():
        position = text.casefold().find(needle)
        left = min(max(position, 0), max(len(text) - 1, 0))
        return _snippet_range(text, left, min(len(text), left + len(needle)))
    # ASCII spans have unit-stride offsets; Unicode spans retain whole clusters.
    chunks = list(_folded_chunks(text))
    position = ''.join(chunk[0] for chunk in chunks).find(needle)
    if position < 0:
        # Rare cross-cluster compatibility composition still has a literal hit.
        position = normalize(text).find(needle)
        left = min(max(position, 0), max(len(text) - 1, 0))
        right = min(len(text), left + len(needle))
    else:
        offset, left, last = 0, None, position + len(needle) - 1
        for folded, start, end, ascii_span in chunks:
            following = offset + len(folded)
            if left is None and position < following:
                left = start + position - offset if ascii_span else start
            if last < following:
                right = start + last - offset + 1 if ascii_span else end
                break
            offset = following
    return _snippet_range(text, left, right)


def _snippet_range(text, left, right):
    begin = max(0, left - 80)
    end = min(len(text), max(right, begin + SNIPPET_CHARS))
    if end - begin > SNIPPET_CHARS:
        begin, end = left, min(len(text), left + SNIPPET_CHARS)
    snippet = ('…' if begin else '') + text[begin:end] + ('…' if end < len(text) else '')
    return snippet, text[left:min(right, end)]


def _validate_page(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Choose a recall limit from 1 to 50')
    if type(offset) is not int or not 0 <= offset <= 9_223_372_036_854_775_807:
        raise ValueError('Choose a recall offset of zero or more')


@contextmanager
def _query_cwds(store):
    """Reuse each stored folder identity only until the locked page is read."""
    previous = getattr(store, '_recall_cwds', None)
    store._recall_cwds = {}
    try:
        yield
    finally:
        store._recall_cwds = previous


@contextmanager
def _read_snapshot(store):
    """Keep recall counts, page and coverage on one caller-safe read snapshot."""
    with store.lock:
        store.db.execute('SAVEPOINT recall_read_snapshot')
        try:
            yield
        finally:
            store.db.execute('RELEASE SAVEPOINT recall_read_snapshot')


def _desk_query(store, scoped, include_archived, needle):
    """The filtered Desk corpus, shared by standalone and mixed-source pages."""
    tables = {row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    activity = """SELECT session_id,'activity' kind,turn_id,item_id,NULL followup_id,
        visible_text text,normalized_text folded,updated,NULL token,NULL status,NULL mode FROM recall_items"""
    if 'native_recall_items' in tables:
        # A scan can finish an item previously copied while it was running.
        # Reply text grows by prefix; command/tool/Plan completion also changes
        # status and structured output. Select one final native result without
        # rewriting the stored row ahead of delayed live delta delivery.
        # Capture time also covers completed tools whose active turn still
        # reports its old startedAt. Later local evidence retains ownership.
        activity = """SELECT i.session_id,'activity' kind,i.turn_id,i.item_id,NULL followup_id,
            coalesce(n.visible_text,i.visible_text) text,
            coalesce(n.normalized_text,i.normalized_text) folded,
            coalesce(max(n.updated,i.updated),i.updated) updated,NULL token,NULL status,NULL mode
            FROM recall_items i JOIN sessions b ON b.id=i.session_id
            LEFT JOIN native_recall_items n ON n.thread_id=b.thread_id
            AND n.turn_id=i.turn_id AND n.item_id=i.item_id AND n.item_type=i.item_type
            AND i.complete=0 AND n.visible_text<>i.visible_text AND (
                (i.item_type='agentMessage' AND instr(n.visible_text,i.visible_text)=1)
                OR (i.item_type NOT IN ('agentMessage','userMessage','subAgentActivity')
                    AND n.complete=1 AND EXISTS (
                        SELECT 1 FROM native_recall_threads c WHERE c.thread_id=n.thread_id
                        AND max(n.updated,c.indexed_at)>=i.updated)))"""
    parts = [activity]
    if 'drafts' in tables:
        parts.append("""SELECT session_id,'draft',NULL,NULL,NULL,text,recall_normalize(text),NULL,NULL,NULL,NULL
            FROM drafts WHERE revision>0 AND trim(text)<>''""")
    if 'followups' in tables:
        parts.append("""SELECT session_id,'followup',NULL,NULL,id,text,recall_normalize(text),NULL,NULL,NULL,NULL
            FROM followups""")
    corpus_options = ()
    if 'events' in tables:
        requests, corpus_options = unresolved_request_query(scoped, include_archived)
        parts.append("""SELECT session_id,'turn_request',NULL,NULL,NULL,text,
            recall_normalize(text),NULL,token,status,mode FROM (""" + requests + ')')
    scope = "s.id<>'native-catalog' AND (? OR s.archived=0) AND (? IS NULL OR recall_cwd(s.cwd)=?)"
    scope_options = (int(include_archived), scoped, scoped)
    options = (*corpus_options, *scope_options)
    corpus = ' UNION ALL '.join(parts)
    joined = f'''FROM ({corpus}) r JOIN sessions s ON s.id=r.session_id WHERE {scope}'''
    counts = {kind: count for kind, count in store.db.execute(
        'SELECT kind,count(*) ' + joined + ' GROUP BY kind', options)}
    sessions = store.db.execute('SELECT count(*) FROM sessions s WHERE ' + scope, scope_options).fetchone()[0]
    total = store.db.execute('SELECT count(*) ' + joined + ' AND instr(r.folded,?)>0',
                             (*options, needle)).fetchone()[0]
    sql = '''SELECT s.id session_id,s.name name,recall_cwd(s.cwd) cwd,s.profile profile,
        s.archived archived,r.kind kind,s.thread_id thread_id,r.turn_id turn_id,
        r.item_id item_id,r.followup_id followup_id,r.text text,
        coalesce(r.updated,s.updated,0) updated,NULL item_type,NULL provider,
        0 source,s.id sort_id,0 position,r.token token,r.status request_status,r.mode request_mode ''' + joined + ' AND instr(r.folded,?)>0'
    coverage = {'text': 'Cached evidence from imported/opened Desk sessions and saved drafts/follow-ups; '
                'not whole native history. Visible activity is cached up to 200,000 characters per item.',
        'sessions': sessions, 'activity_items': counts.get('activity', 0),
        'drafts': counts.get('draft', 0), 'followups': counts.get('followup', 0)}
    if counts.get('turn_request'):
        coverage['turn_requests'] = counts['turn_request']
        coverage['text'] = coverage['text'].replace('saved drafts/follow-ups;',
            'saved drafts/follow-ups and unresolved captured task requests;')
    return sql, (*options, needle), total, coverage


PAGE_ORDER = ' ORDER BY updated DESC,source,sort_id,kind,position,turn_id,item_id,followup_id LIMIT ? OFFSET ?'


def _search_result(row, needle, *, combined=False):
    (session, name, project, profile, archived, kind, thread, turn, item,
     followup, text, updated, item_type, provider, *_) = row
    snippet, match = _snippet(text, needle)
    if kind == 'native-activity':
        result = {'kind': kind, 'thread_id': thread, 'cwd': project, 'title': name,
                  'provider': provider, 'turn_id': turn, 'item_id': item,
                  'item_type': item_type, 'snippet': snippet, 'match_text': match, 'updated': updated}
        if combined:
            result.update(name=name, profile='default', archived=False)
    elif kind == 'turn_request':
        token, status, mode = _[-3:]
        result = {'session_id': session, 'session_name': name, 'cwd': project,
                  'profile': profile, 'archived': bool(archived), 'kind': kind,
                  'token': token, 'status': status, 'mode': mode, 'snippet': snippet,
                  'match_text': match, 'updated': updated}
    else:
        result = {'session_id': session, 'session_name': name, 'cwd': project,
                  'profile': profile, 'archived': bool(archived), 'kind': kind, 'turn_id': turn,
                  'item_id': item, 'followup_id': followup, 'snippet': snippet,
                  'match_text': match, 'updated': updated}
        if combined and kind == 'activity' and thread is not None:
            result['thread_id'] = thread
    return result


def search(store, q, cwd=None, include_archived=False, limit=30, offset=0):
    if not isinstance(q, str) or not 2 <= len(q.strip()) <= 200:
        raise ValueError('Enter a recall phrase of 2–200 characters')
    q = q.strip()
    try:
        q.encode('utf-8')
    except UnicodeEncodeError:
        raise ValueError('Enter valid Unicode recall text') from None
    _validate_page(limit, offset)
    if type(include_archived) is not bool:
        raise ValueError('Choose whether to include archived sessions')
    if cwd is not None and (not isinstance(cwd, str) or not cwd.strip()):
        raise ValueError('Choose a project folder')
    scoped = canonical_cwd(cwd) if cwd is not None else None
    needle = normalize(q)
    with _read_snapshot(store), _query_cwds(store):
        sql, options, total, coverage = _desk_query(store, scoped, include_archived, needle)
        cursor = store.db.execute(sql + PAGE_ORDER, (*options, limit, offset))
        results = [_search_result(row, needle) for row in cursor]
    return {'query': q, 'cwd': scoped, 'archived': include_archived, 'limit': limit,
        'offset': offset, 'total': total, 'truncated': total > len(results),
        'has_more': offset + len(results) < total, 'results': results, 'coverage': coverage}
