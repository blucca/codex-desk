"""Compact parent-native material frontiers from the retained local event log."""
import json

ITEM_TYPES = frozenset(('userMessage', 'agentMessage', 'plan', 'commandExecution',
    'fileChange', 'mcpToolCall', 'dynamicToolCall', 'collabAgentToolCall', 'subAgentActivity'))
METHODS = ('turn/started', 'turn/completed', 'item/started', 'item/completed',
    'item/agentMessage/delta', 'item/commandExecution/outputDelta',
    'item/plan/delta', 'item/mcpToolCall/progress')
# Match JavaScript String.trim, including the native producer's Unicode whitespace.
SPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
METHOD = "CASE WHEN json_valid(payload) THEN json_extract(payload,'$.method') END"
CANDIDATES = METHOD + ' IN (' + ','.join(repr(method) for method in METHODS) + ')'


def initialize(store):
    store.db.execute('CREATE INDEX IF NOT EXISTS native_material_events '
        'ON events(session_id,seq)')


def _identifier(value):
    return isinstance(value, str) and bool(value.strip(SPACE)) and len(value) <= 200


def summaries(store, sessions, native_home):
    """Read compact IDs/flags only; transport, material and source stay separate.

    Reprojects the authoritative log on each state read. No body/cache/native
    read or review boundary is returned or written here.
    """
    bound = {row['id']: row['thread_id'] for row in sessions
        if row['id'] != 'native-catalog' and _identifier(row.get('thread_id'))}
    if not bound:
        return []
    material = dict.fromkeys(bound, 0)
    selected = 'session_id IN (' + ','.join('?' for _ in bound) + ')'
    bindings = tuple(bound)
    current_turn, plans = {}, {}
    with store.lock:
        received = dict(store.db.execute('SELECT session_id,max(seq) FROM events WHERE ' + selected + ' GROUP BY session_id', bindings))
        # Empty/start plans affect later delta eligibility without themselves
        # being readable material. Extract flags in SQL, never message/tool text.
        rows = store.db.execute('''SELECT seq,session_id,
            json_extract(payload,'$.method'),json_type(payload,'$.id') IS NOT NULL,
            CASE WHEN json_type(payload,'$.params.threadId')='text' THEN json_extract(payload,'$.params.threadId') END,
            CASE WHEN json_type(payload,'$.params.turnId')='text' THEN json_extract(payload,'$.params.turnId') END,
            CASE WHEN json_type(payload,'$.params.turn.id')='text' THEN json_extract(payload,'$.params.turn.id') END,
            CASE WHEN json_type(payload,'$.params.item.id')='text' THEN json_extract(payload,'$.params.item.id') END,
            json_extract(payload,'$.params.item.type'),
            CASE WHEN json_type(payload,'$.params.itemId')='text' THEN json_extract(payload,'$.params.itemId') END,
            json_type(payload,'$.params.itemId') IS NOT NULL,
            CASE WHEN json_type(payload,'$.params.item.text')='text'
                THEN length(trim(json_extract(payload,'$.params.item.text'),?))>0 ELSE 0 END,
            EXISTS(SELECT 1 FROM json_each(CASE
                WHEN json_type(payload,'$.params.item.content')='array'
                THEN json_extract(payload,'$.params.item.content') ELSE '[]' END) part
                WHERE part.type='object' AND json_extract(part.value,'$.type')='text'
                AND json_type(part.value,'$.text')='text' AND length(trim(json_extract(part.value,'$.text'),?))>0),
            CASE WHEN json_type(payload,'$.params.delta')='text'
                THEN length(json_extract(payload,'$.params.delta'))>0 ELSE 0 END,
            CASE WHEN json_type(payload,'$.params.message')='text'
                THEN length(json_extract(payload,'$.params.message'))>0 ELSE 0 END,
            (SELECT json_group_array(json_extract(part.value,'$.id'))
                FROM json_each(CASE WHEN json_type(payload,'$.params.turn.items')='array'
                THEN json_extract(payload,'$.params.turn.items') ELSE '[]' END) part
                WHERE part.type='object' AND json_extract(part.value,'$.type')='plan'
                AND json_type(part.value,'$.id')='text')
            FROM events INDEXED BY native_material_events WHERE ''' + selected + ' AND ' + CANDIDATES + ' ORDER BY session_id,seq', (SPACE, SPACE, *bindings))
        for (seq, session, method, request, thread, turn_id, turn, item_id, item_type,
                delta_id, delta_id_present, text, content, delta, progress, final_plans) in rows:
            if session not in bound or (thread and thread != bound[session]):
                continue
            owned_plans = plans.setdefault(session, {})
            active_turn = current_turn.get(session)
            turn_identity = turn or turn_id
            readable = False
            if method in ('item/started', 'item/completed'):
                readable = (item_type in ITEM_TYPES and _identifier(item_id)
                    and (not delta_id_present or delta_id == item_id)
                    and (bool(text) if item_type in ('agentMessage', 'plan')
                         else bool(content) if item_type == 'userMessage' else True))
            elif method in ('item/agentMessage/delta', 'item/commandExecution/outputDelta'):
                readable = bool(delta) and _identifier(delta_id)
            elif method == 'item/mcpToolCall/progress':
                readable = bool(progress) and _identifier(delta_id)
            elif method == 'item/plan/delta':
                readable = (bool(delta) and _identifier(delta_id) and turn_id == active_turn
                    and owned_plans.get(delta_id) == (turn_id, 'streaming'))
            if not request and thread == bound[session] and _identifier(turn_id) and readable:
                material[session] = seq
            # Mirror the selected-task consumer's streaming-plan eligibility.
            if method == 'turn/started':
                next_turn = turn_identity or active_turn
                if active_turn and next_turn != active_turn:
                    for key, value in list(owned_plans.items()):
                        if value == (active_turn, 'streaming'):
                            owned_plans[key] = (active_turn, 'retired')
                current_turn[session] = next_turn
            elif method in ('item/started', 'item/completed') and _identifier(item_id):
                if item_type == 'plan':
                    owned_plans[item_id] = (turn_id, 'complete' if method == 'item/completed' else 'streaming')
                else:
                    owned_plans.pop(item_id, None)
            elif method == 'turn/completed':
                for key in json.loads(final_plans):
                    if _identifier(key):
                        owned_plans[key] = (turn_identity, 'complete')
                for key, value in list(owned_plans.items()):
                    if value == (turn_identity, 'streaming'):
                        owned_plans[key] = (turn_identity, 'complete')
    return [{'owner': {'native_home': native_home, 'session': session, 'thread_id': thread},
        'status': 'available', 'received_seq': received.get(session, 0), 'material_seq': material[session]}
        for session, thread in bound.items()]
