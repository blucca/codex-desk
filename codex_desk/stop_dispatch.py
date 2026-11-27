"""Stop one captured native task; retained receipts never resend it."""
import json
import os
from pathlib import Path
import uuid
from .handoff_dispatch import validate_handoff_home
from .runtime import active_turn_id, _thread_scope, NativeRequestRejected

INTENT = 'desk/stopIntent'
RECEIPT = 'desk/stopReceipt'
OWNER = ('session', 'native_home', 'profile', 'cwd', 'thread_id')


class StopConflict(ValueError):
    def __init__(self, current, message='Check the captured Stop request before stopping this task again'):
        self.current = current
        super().__init__(message)


def _token(value):
    if not isinstance(value, str):
        raise ValueError('Use the Stop request ID')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ValueError('Use the Stop request ID') from None
    if str(parsed) != value:
        raise ValueError('Use the Stop request ID')
    return value


def _payload(data):
    if not isinstance(data, dict) or set(data) != {'session', 'token', 'threadId', 'expectedTurnId'}:
        raise ValueError('Use one captured Stop request')
    _token(data['token'])
    for key in ('session', 'threadId', 'expectedTurnId'):
        if not isinstance(data[key], str) or not data[key].strip() or len(data[key]) > 200:
            raise ValueError('Select the active native task')
    return dict(data)


def _binding(desk, session):
    if not isinstance(session, str) or not session or session == 'native-catalog':
        raise ValueError('Select an existing project session')
    row = desk.store.get(session)
    if row is None:
        raise ValueError('Session not found')
    return {'session': session, 'native_home': os.path.normcase(str(desk.home.resolve())),
            'profile': row['profile'], 'cwd': row['cwd'], 'thread_id': row['thread_id'],
            'turn_id': active_turn_id(desk.store, session, row['thread_id'])}


def _records(desk, session):
    with desk.store.lock:
        rows = desk.store.db.execute(
            "SELECT payload FROM events WHERE session_id=? AND json_extract(payload,'$.method') IN (?,?) ORDER BY seq",
            (session, INTENT, RECEIPT)).fetchall()
    intents, receipts = {}, {}
    for (raw,) in rows:
        event = json.loads(raw)
        (intents if event['method'] == INTENT else receipts)[event['params']['token']] = event['params']
    return intents, receipts


def _terminal_status(desk, payload):
    with desk.store.lock:
        rows = desk.store.db.execute(
            "SELECT payload FROM events WHERE session_id=? AND json_extract(payload,'$.method')='turn/completed' ORDER BY seq DESC",
            (payload['session'],)).fetchall()
    for (raw,) in rows:
        event = json.loads(raw)
        if 'id' in event:
            continue
        params = event.get('params') or {}
        turn = params.get('turn') or {}
        scope = _thread_scope(params) or turn.get('threadId')
        if scope and scope != payload['threadId']:
            continue
        if (turn.get('id') or params.get('turnId')) != payload['expectedTurnId']:
            continue
        status = turn.get('status')
        if status in ('completed', 'interrupted', 'failed'):
            return status
    return None


def _snapshot(desk, intent, receipt):
    payload, captured = intent['payload'], intent['binding']
    session, token = payload['session'], payload['token']
    state = dict(receipt or {'status': 'pending'})
    state.pop('token', None)
    if state['status'] == 'pending' and desk.stop_sends.get(session) != token:
        state.update(status='needs_review', error='No confirmed Stop receipt. Check the captured request.')
    current = _binding(desk, session)
    mismatch = any(current[key] != captured[key] for key in OWNER)
    state.update(payload=dict(payload), binding=dict(captured), current_binding=current,
                 binding_mismatch=mismatch,
                 target_current=not mismatch and current['thread_id'] == payload['threadId']
                     and current['turn_id'] == payload['expectedTurnId'],
                 terminal_status=_terminal_status(desk, payload))
    return {'session': session, 'token': token, 'request': state}


def stop_status(desk, session, token=None):
    """Store-only receipt recovery, including disconnected cold owners."""
    if token is not None:
        token = _token(token)
    with desk.lock:
        _binding(desk, session)
        intents, receipts = _records(desk, session)
        if token is None:
            token = next((key for key in reversed(intents)
                          if receipts.get(key, {}).get('status', 'pending') in ('pending', 'needs_review')), None)
        intent = intents.get(token)
        return _snapshot(desk, intent, receipts.get(token)) if intent else None


def _receipt(desk, session, token, status, **fields):
    desk.store.event(session, {'method': RECEIPT, 'params': {'token': token, 'status': status, **fields}})


def start_stop(desk, data):
    payload = _payload(data)
    session, token = payload['session'], payload['token']
    with desk.lock:
        current = _binding(desk, session)
        intents, receipts = _records(desk, session)
        if token in intents:
            saved = _snapshot(desk, intents[token], receipts.get(token))
            if intents[token]['payload'] != payload:
                raise StopConflict(saved, 'Use a new Stop request ID for a changed native target')
            return saved
        with desk.store.lock:
            other = desk.store.db.execute(
                "SELECT session_id FROM events WHERE session_id<>? AND json_extract(payload,'$.method')=? "
                "AND json_extract(payload,'$.params.token')=? LIMIT 1", (session, INTENT, token)).fetchone()
        if other:
            raise StopConflict(stop_status(desk, other[0], token), 'Use a new Stop request ID for a different project')
        for old, intent in intents.items():
            if (receipts.get(old, {}).get('status', 'pending') in ('pending', 'needs_review')
                    and all(intent['binding'][key] == current[key] for key in OWNER)
                    and current['thread_id'] == payload['threadId'] == intent['payload']['threadId']
                    and current['turn_id'] == payload['expectedTurnId'] == intent['payload']['expectedTurnId']):
                raise StopConflict(_snapshot(desk, intent, receipts.get(old)))
        binding = {**current, 'turn_id': payload['expectedTurnId']}
        runtime, held, error = desk.runtimes.get(session), False, None
        try:
            validate_handoff_home(desk, session)
            if current['thread_id'] != payload['threadId'] or current['turn_id'] != payload['expectedTurnId']:
                raise ValueError('The captured native task is no longer active')
            if (runtime is None or runtime.closing or runtime.process.poll() is not None
                    or runtime.store is not desk.store or runtime.id != session
                    or Path(runtime.home).resolve() != desk.home.resolve()):
                raise ValueError('The selected native task is not already connected')
            if session in desk.stop_sends:
                raise ValueError('Another Stop request is still pending')
            # Stop remains available while a task/steer acknowledgement waits.
            # Only another in-flight Stop owns this separate claim.
            desk.stop_sends[session] = token
            held = True
        except ValueError as failure:
            error = str(failure)
        try:
            desk.store.event(session, {'method': INTENT, 'params': {'token': token, 'payload': payload, 'binding': binding}})
            _receipt(desk, session, token, 'rejected' if error else 'pending', **({'error': error} if error else {}))
        except Exception:
            if held:
                desk.stop_sends.pop(session, None)
            raise
        if error:
            return stop_status(desk, session, token)
    try:
        try:
            result = runtime.interrupt(payload['threadId'], payload['expectedTurnId'])
            outcome, fields = 'accepted', {'result': result}
        except (NativeRequestRejected, ValueError) as failure:
            outcome, fields = 'rejected', {'error': str(failure)}
        except Exception as failure:
            outcome, fields = 'needs_review', {'error': str(failure)}
        with desk.lock:
            _receipt(desk, session, token, outcome, **fields)
            return stop_status(desk, session, token)
    finally:
        with desk.lock:
            if desk.stop_sends.get(session) == token:
                desk.stop_sends.pop(session)


def stop_current(desk, data):
    """Legacy explicit scripting keeps its ACK shape, not implicit opening."""
    if not isinstance(data, dict) or set(data) != {'session'}:
        return start_stop(desk, data)
    with desk.lock:
        current = _binding(desk, data['session'])
        if not current['turn_id']:
            raise ValueError('No active native task')
        payload = {'session': data['session'], 'token': str(uuid.uuid4()),
                   'threadId': current['thread_id'], 'expectedTurnId': current['turn_id']}
    state = start_stop(desk, payload)['request']
    if state['status'] != 'accepted':
        raise ValueError(state.get('error', 'Check the captured Stop receipt'))
    return state['result']
