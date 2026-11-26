"""Bounded literal recall of native histories, independent of Desk bindings."""
import time

from .recall import (MAX_ITEM_CHARS, VISIBLE_TYPES, _item_text, _snippet,
                     _timestamp, canonical_cwd, normalize)


MAX_THREAD_CHARS = 2_000_000
MAX_THREAD_ITEMS = 5_000
_COUNT_FIELDS = ('source_turns', 'source_items', 'readable_items', 'indexed_items',
                 'indexed_chars', 'omitted_items', 'unsupported_items', 'invalid_items',
                 'shortened_items', 'item_limit_hits')


def _string(value, limit):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return None
    return value[:limit]


def _identifier(value):
    return _string(value, 200) == value and isinstance(value, str) and bool(value.strip())


def _scope(cwd):
    if cwd is None:
        return None
    if _string(cwd, 4096) != cwd:
        raise ValueError('Choose a project folder')
    return canonical_cwd(cwd)


def _native_timestamp(value, fallback):
    try:
        return _timestamp(value, fallback)
    except (OverflowError, ValueError, TypeError):
        return fallback


def _metadata(thread, previous=None):
    previous = previous or (None, thread['id'], None, 0)
    cwd = _string(thread.get('cwd'), 4096)
    title = next((value for key in ('name', 'title', 'preview')
                  if (value := _string(thread.get(key), 240)) is not None), None)
    provider = next((value for key in ('modelProvider', 'provider')
                     if (value := _string(thread.get(key), 160)) is not None), None)
    return (canonical_cwd(cwd) if cwd is not None else previous[0],
            title if title is not None else previous[1],
            provider if provider is not None else previous[2],
            _native_timestamp(thread.get('updatedAt'), previous[3]))


class NativeRecallIndex:
    """Copies only shared-sanitizer visible text; never creates a Desk session.

    A list-valued ``turns`` is an authoritative full history read. Metadata-only
    snapshots preserve all cached items and the last full-read freshness marker.
    Native turns/items are supplied oldest first; storage retains newest items.
    """

    def __init__(self, store, *, max_thread_chars=MAX_THREAD_CHARS,
                 max_thread_items=MAX_THREAD_ITEMS):
        if type(max_thread_chars) is not int or not 1 <= max_thread_chars <= MAX_THREAD_CHARS:
            raise ValueError('Choose a native recall character limit from 1 to 2000000')
        if type(max_thread_items) is not int or not 1 <= max_thread_items <= MAX_THREAD_ITEMS:
            raise ValueError('Choose a native recall item limit from 1 to 5000')
        self.store = store
        self.max_thread_chars, self.max_thread_items = max_thread_chars, max_thread_items
        self.ensure_schema()

    def ensure_schema(self):
        with self.store.lock, self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS native_recall_threads(
                thread_id TEXT PRIMARY KEY NOT NULL, cwd TEXT, title TEXT NOT NULL,
                provider TEXT, updated REAL NOT NULL,
                snapshot_updated REAL, snapshot_cwd TEXT, snapshot_title TEXT,
                snapshot_provider TEXT, indexed_at REAL,
                char_limit INTEGER NOT NULL DEFAULT 0, item_limit INTEGER NOT NULL DEFAULT 0,
                source_turns INTEGER NOT NULL DEFAULT 0, source_items INTEGER NOT NULL DEFAULT 0,
                readable_items INTEGER NOT NULL DEFAULT 0, indexed_items INTEGER NOT NULL DEFAULT 0,
                indexed_chars INTEGER NOT NULL DEFAULT 0, omitted_items INTEGER NOT NULL DEFAULT 0,
                unsupported_items INTEGER NOT NULL DEFAULT 0, invalid_items INTEGER NOT NULL DEFAULT 0,
                shortened_items INTEGER NOT NULL DEFAULT 0, item_limit_hits INTEGER NOT NULL DEFAULT 0)''')
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS native_recall_items(
                thread_id TEXT NOT NULL, turn_id TEXT NOT NULL, item_id TEXT NOT NULL,
                item_type TEXT NOT NULL, visible_text TEXT NOT NULL, normalized_text TEXT NOT NULL,
                updated REAL NOT NULL, position INTEGER NOT NULL,
                PRIMARY KEY(thread_id,turn_id,item_id))''')
            self.store.db.execute('CREATE INDEX IF NOT EXISTS native_recall_cwd ON native_recall_threads(cwd)')
            self.store.db.execute('''CREATE INDEX IF NOT EXISTS native_recall_recent
                ON native_recall_items(updated DESC,thread_id,position)''')

    def _previous(self, thread_id):
        return self.store.db.execute('''SELECT cwd,title,provider,updated FROM native_recall_threads
            WHERE thread_id=?''', (thread_id,)).fetchone()

    def needs_snapshot(self, metadata):
        """Whether metadata differs from the last full read; survives cold reopen."""
        if not isinstance(metadata, dict) or not _identifier(metadata.get('id')):
            raise ValueError('Choose a native thread')
        timestamp = _native_timestamp(metadata.get('updatedAt'), None)
        if timestamp is None:
            return True
        with self.store.lock:
            previous = self._previous(metadata['id'])
            row = self.store.db.execute('''SELECT snapshot_cwd,snapshot_title,snapshot_provider,
                snapshot_updated,indexed_at,char_limit,item_limit FROM native_recall_threads
                WHERE thread_id=?''', (metadata['id'],)).fetchone()
            current = _metadata(metadata, previous)
            return (row is None or row[4] is None or current != row[:4]
                    or row[5:] != (self.max_thread_chars, self.max_thread_items))

    def replace_snapshot(self, thread):
        """Atomically replace a full read, or update metadata without erasing text."""
        if not isinstance(thread, dict) or not _identifier(thread.get('id')):
            raise ValueError('Choose a native thread')
        thread_id = thread['id']
        with self.store.lock, self.store.db:
            metadata = _metadata(thread, self._previous(thread_id))
            self.store.db.execute('''INSERT INTO native_recall_threads
                (thread_id,cwd,title,provider,updated) VALUES(?,?,?,?,?)
                ON CONFLICT(thread_id) DO UPDATE SET cwd=excluded.cwd,title=excluded.title,
                provider=excluded.provider,updated=excluded.updated''', (thread_id, *metadata))
            turns = thread.get('turns')
            if isinstance(turns, list):
                rows, counts = self._readable_rows(thread_id, turns, metadata[3])
                self.store.db.execute('DELETE FROM native_recall_items WHERE thread_id=?', (thread_id,))
                self.store.db.executemany('''INSERT INTO native_recall_items
                    (thread_id,turn_id,item_id,item_type,visible_text,normalized_text,updated,position)
                    VALUES(?,?,?,?,?,?,?,?)''', rows)
                assignments = ','.join(field + '=?' for field in _COUNT_FIELDS)
                self.store.db.execute('''UPDATE native_recall_threads SET
                    snapshot_cwd=?,snapshot_title=?,snapshot_provider=?,snapshot_updated=?,
                    indexed_at=?,char_limit=?,item_limit=?,''' + assignments + ' WHERE thread_id=?',
                    (*metadata[:3], _native_timestamp(thread.get('updatedAt'), None), time.time(),
                     self.max_thread_chars, self.max_thread_items,
                     *(counts[field] for field in _COUNT_FIELDS), thread_id))
            return self._thread_stats(thread_id)

    def _readable_rows(self, thread_id, turns, updated):
        rows, seen = [], set()
        counts = dict.fromkeys(_COUNT_FIELDS, 0)
        for turn in reversed(turns):
            if not isinstance(turn, dict) or not _identifier(turn.get('id')):
                continue
            counts['source_turns'] += 1
            items = turn.get('items')
            if not isinstance(items, list):
                continue
            stamp = _native_timestamp(turn.get('completedAt') or turn.get('startedAt'), updated)
            for item in reversed(items):
                counts['source_items'] += 1
                if not isinstance(item, dict) or not isinstance(item.get('type'), str) or item['type'] not in VISIBLE_TYPES:
                    counts['unsupported_items'] += 1
                    continue
                if not _identifier(item.get('id')):
                    counts['invalid_items'] += 1
                    continue
                key = (turn['id'], item['id'])
                if key in seen:
                    continue
                seen.add(key)
                text = _item_text(item)
                try:
                    text.encode('utf-8')
                except UnicodeEncodeError:
                    counts['invalid_items'] += 1
                    continue
                if not text:
                    counts['invalid_items'] += 1
                    continue
                counts['readable_items'] += 1
                at_item_limit = len(text) == MAX_ITEM_CHARS
                remaining = self.max_thread_chars - counts['indexed_chars']
                if remaining <= 0 or len(rows) >= self.max_thread_items:
                    counts['omitted_items'] += 1
                    continue
                shortened = len(text) > remaining
                text = text[:remaining]
                counts['shortened_items'] += int(shortened)
                counts['item_limit_hits'] += int(at_item_limit)
                counts['indexed_chars'] += len(text)
                rows.append((thread_id, turn['id'], item['id'], item['type'], text,
                             normalize(text), stamp, len(rows)))
        counts['indexed_items'] = len(rows)
        return rows, counts

    def _thread_stats(self, thread_id):
        row = self.store.db.execute('SELECT indexed_at,char_limit,item_limit,' + ','.join(_COUNT_FIELDS)
                                   + ' FROM native_recall_threads WHERE thread_id=?', (thread_id,)).fetchone()
        result = dict(zip(_COUNT_FIELDS, row[3:]))
        result.update(thread_id=thread_id, indexed_at=row[0], char_limit=row[1], item_limit=row[2],
                      indexed=row[0] is not None,
                      truncated=bool(result['omitted_items'] or result['shortened_items'] or result['item_limit_hits']))
        return result

    def _stats(self, scoped):
        where = ' WHERE (? IS NULL OR cwd=?)'
        counts = ','.join('coalesce(sum(' + field + '),0)' for field in _COUNT_FIELDS)
        row = self.store.db.execute('''SELECT count(*),coalesce(sum(indexed_at IS NOT NULL),0),
            coalesce(sum(omitted_items>0 OR shortened_items>0 OR item_limit_hits>0),0),'''
            + counts + ' FROM native_recall_threads' + where, (scoped, scoped)).fetchone()
        return {'threads': row[0], 'indexed_threads': row[1], 'metadata_only_threads': row[0] - row[1],
                'truncated_threads': row[2], **dict(zip(_COUNT_FIELDS, row[3:])),
                'max_thread_chars': self.max_thread_chars, 'max_thread_items': self.max_thread_items,
                'max_item_chars': MAX_ITEM_CHARS,
                'text': 'Cached visible text from native history reads, newest items first; '
                        'coverage counts describe the supplied native snapshots.'}

    def stats(self, cwd=None):
        scoped = _scope(cwd)
        with self.store.lock:
            return self._stats(scoped)

    def search(self, query, cwd=None, limit=30, *, exclude_thread_ids=()):
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 200:
            raise ValueError('Enter a recall phrase of 2–200 characters')
        query = query.strip()
        try:
            query.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('Enter valid Unicode recall text') from None
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Choose a recall limit from 1 to 50')
        if isinstance(exclude_thread_ids, (str, bytes)):
            raise ValueError('Choose original thread identifiers to exclude')
        excluded = tuple(dict.fromkeys(exclude_thread_ids))
        if any(not isinstance(v, str) or not 0 < len(v) <= 200 for v in excluded):
            raise ValueError('Choose original thread identifiers to exclude')
        scoped, needle = _scope(cwd), normalize(query)
        with self.store.lock:
            joined = '''FROM native_recall_items i JOIN native_recall_threads t ON t.thread_id=i.thread_id
                WHERE (? IS NULL OR t.cwd=?) AND instr(i.normalized_text,?)>0'''
            options = (scoped, scoped, needle)
            if excluded:
                joined += ' AND t.thread_id NOT IN (' + ','.join('?' for _ in excluded) + ')'
                options += excluded
            total = self.store.db.execute('SELECT count(*) ' + joined, options).fetchone()[0]
            cursor = self.store.db.execute('''SELECT t.thread_id,t.cwd,t.title,t.provider,
                i.turn_id,i.item_id,i.item_type,i.visible_text,i.updated ''' + joined + '''
                ORDER BY i.updated DESC,t.thread_id,i.position,i.turn_id,i.item_id LIMIT ?''', (*options, limit))
            results = []
            for thread_id, project, title, provider, turn, item, kind, text, updated in cursor:
                snippet, match = _snippet(text, needle)
                results.append({'kind': 'native-activity', 'thread_id': thread_id, 'cwd': project,
                                'title': title, 'provider': provider, 'turn_id': turn, 'item_id': item,
                                'item_type': kind, 'snippet': snippet, 'match_text': match, 'updated': updated})
            return {'query': query, 'cwd': scoped, 'limit': limit, 'total': total,
                    'truncated': total > len(results), 'results': results, 'coverage': self._stats(scoped)}
