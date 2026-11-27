"""Retained ordinary Run admissions in the existing private event stream.

The UUID identifies one captured task, not its words. Recovery never opens a
native session; only a fresh request or explicit known-rejected retry dispatches.
"""
import json
import os
from pathlib import Path
import uuid

from .drafts import MAX_DRAFT_CHARS, clear_admitted_draft, draft_snapshot
from .followups import FollowupConflict, followup_snapshot
from .handoff_dispatch import validate_handoff_home
from .runtime import NativeRequestRejected

_INTENT = 'desk/turnIntent'
_RECEIPT = 'desk/turnReceipt'


class TurnConflict(ValueError):
    def __init__(self, current, message='Review the retained task request before sending another task'):
        self.current = current
        super().__init__(message)


def _token(value):
    if not isinstance(value, str):
        raise ValueError('Use the ordinary task request ID')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ValueError('Use the ordinary task request ID') from None
    if str(parsed) != value:
        raise ValueError('Use the ordinary task request ID')
    return value


def _binding(desk, session):
    if not isinstance(session, str) or not session or session == 'native-catalog':
        raise ValueError('Select an existing project session')
    row = desk.store.get(session)
    if row is None:
        raise ValueError('Session not found')
    return {'session': session,
            'native_home': os.path.normcase(str(Path(desk.home).expanduser().resolve())),
            'profile': row['profile'], 'cwd': row['cwd'], 'thread_id': row['thread_id']}


def _payload(data):
    token = _token(data.get('token'))
    text = data.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_DRAFT_CHARS:
        raise ValueError(f'Enter a project task of 1–{MAX_DRAFT_CHARS:,} characters')
    if data.get('mode') not in ('native', 'plan'):
        raise ValueError('Choose Work or Plan mode')
    if type(data.get('revision')) is not int or data['revision'] < 0:
        raise ValueError('Use a nonnegative draft revision')
    if (not isinstance(data.get('writer'), str) or not data['writer'] or len(data['writer']) > 128
            or type(data.get('sequence')) is not int or not 0 <= data['sequence'] <= 2**63 - 1):
        raise ValueError('Use a page writer ID and a nonnegative edit sequence')
    if 'retry' in data and type(data['retry']) is not bool:
        raise ValueError('Choose an explicit rejected-task retry')
    return {key: data[key] for key in ('session', 'token', 'text', 'mode', 'revision', 'writer', 'sequence')}


def _records(desk, session):
    intents, receipts = {}, {}
    for record in desk.store.events(session):
        event = record['event']
        if event.get('method') not in (_INTENT, _RECEIPT):
            continue
        params = event.get('params', {})
        if event['method'] == _INTENT:
            intents[params['token']] = params
        else:
            receipts[params['token']] = params
    return intents, receipts


def _other_session(desk, session, token):
    # A reused UUID cannot move a captured request into a different project.
    with desk.store.lock:
        rows = desk.store.db.execute(
            'SELECT session_id,payload FROM events WHERE session_id<>? AND payload LIKE ?',
            (session, '%' + token + '%')).fetchall()
    return next((owner for owner, raw in rows if json.loads(raw).get('method') == _INTENT
                 and json.loads(raw).get('params', {}).get('token') == token), None)


def _validate_binding(desk, intent):
    if _binding(desk, intent['payload']['session']) != intent['binding']:
        raise ValueError('Reopen the original native home and session binding to review this task request')


def _snapshot(desk, intent, receipt):
    _validate_binding(desk, intent)
    session, token = intent['payload']['session'], intent['token']
    state = dict(receipt or {'token': token, 'status': 'pending', 'attempt': 1})
    state.pop('token', None)
    gate = desk.admissions.get(session)
    if state['status'] == 'pending' and (gate is None or not gate.locked()):
        state.update(status='needs_review', error='No completed admission receipt. Review this captured task before sending another task.')
    state.update(payload=dict(intent['payload']), binding=dict(intent['binding']))
    if state['status'] == 'accepted':
        state['draft'] = draft_snapshot(desk.store, session)
    return {'session': session, 'token': token, 'request': state}


def turn_status(desk, session, token):
    """Cold private receipt read: no native open, dispatch, draft or event write."""
    token = _token(token)
    with desk.lock:
        _binding(desk, session)
        intents, receipts = _records(desk, session)
        intent = intents.get(token)
        return _snapshot(desk, intent, receipts.get(token)) if intent else None


def block_unresolved_turn(desk, session):
    """The shared gate also excludes anonymous Run and prepared Send next."""
    with desk.lock:
        intents, receipts = _records(desk, session)
        for token, intent in intents.items():
            receipt = receipts.get(token)
            if receipt is None or receipt['status'] in ('pending', 'needs_review'):
                raise TurnConflict(_snapshot(desk, intent, receipt))


def _receipt(desk, session, token, status, attempt, **fields):
    state = {'token': token, 'status': status, 'attempt': attempt, **fields}
    desk.store.event(session, {'method': _RECEIPT, 'params': state})
    return state


def _retain_rejection(desk, payload, binding, intent, previous, error):
    """A valid captured task denied before dispatch still has a cold receipt."""
    session, token = payload['session'], payload['token']
    if intent is None:
        intent = {'token': token, 'payload': payload, 'binding': binding}
        desk.store.event(session, {'method': _INTENT, 'params': intent})
    _receipt(desk, session, token, 'rejected', previous['attempt'] + 1 if previous else 1,
             error=str(error))
    return turn_status(desk, session, token)


def start_turn(desk, data):
    """Dispatch once, then recover by identity even after native completion."""
    payload = _payload(data)
    session, token = payload['session'], payload['token']
    gate = desk.admission_lock(session)
    with desk.lock:
        binding = _binding(desk, session)
        intents, receipts = _records(desk, session)
        intent, previous = intents.get(token), receipts.get(token)
        if intent is not None:
            current = _snapshot(desk, intent, previous)
            if intent['payload'] != payload:
                raise TurnConflict(current, 'Use a new request ID for a changed task or draft revision')
            if not data.get('retry'):
                return current
            if current['request']['status'] != 'rejected':
                raise TurnConflict(current, 'Only a known rejected task can be explicitly retried')
        else:
            owner = _other_session(desk, session, token)
            if owner:
                raise TurnConflict(turn_status(desk, owner, token), 'Use a new request ID for a different project session')
            if data.get('retry'):
                raise ValueError('Recover the rejected request before retrying it')
        block_unresolved_turn(desk, session)
        if not gate.acquire(blocking=False):
            return _retain_rejection(desk, payload, binding, intent, previous,
                                     ValueError('Finish or stop the current turn first'))
        try:
            validate_handoff_home(desk, session)
            snapshot = followup_snapshot(desk.store, session)
            if snapshot['reservation']:
                raise FollowupConflict(snapshot)
            attempt = previous['attempt'] + 1 if previous else 1
            if intent is None:
                intent = {'token': token, 'payload': payload, 'binding': binding}
                desk.store.event(session, {'method': _INTENT, 'params': intent})
            _receipt(desk, session, token, 'pending', attempt)
        except ValueError as failure:
            gate.release()
            return _retain_rejection(desk, payload, binding, intent, previous, failure)
        except Exception:
            gate.release()
            raise
    runtime, invoked, result, error, rejected = None, False, None, None, False
    try:
        try:
            runtime = desk.runtime(session)
            with desk.lock:
                attached = _binding(desk, session)
                if attached != intent['binding']:
                    # A fresh blank may receive its first native binding on
                    # attach. Capture it before dispatch, never on a retry.
                    scope = ('session', 'native_home', 'profile', 'cwd')
                    if (previous or intent['binding']['thread_id'] is not None
                            or any(attached[k] != intent['binding'][k] for k in scope)):
                        raise ValueError('The retained native target changed before admission')
                    intent = {**intent, 'binding': attached}
                    desk.store.event(session, {'method': _INTENT, 'params': intent})
                records = desk.store.events(session)
                cursor = records[-1]['seq'] if records else 0
            invoked = True
            result = runtime.turn(payload['text'], payload['mode'])
            turn = result.get('turn') if isinstance(result, dict) else None
            if not (isinstance(turn, dict) and isinstance(turn.get('id'), str) and turn['id']):
                result = desk.started_since(session, cursor)
                if result is None:
                    error = 'Native task admission is unconfirmed; review this receipt before sending another task'
        except Exception as failure:
            error = str(failure)
            rejected = not invoked or isinstance(failure, (NativeRequestRejected, ValueError))
            result = desk.started_since(session, cursor) if invoked and not rejected else None
        outcome = 'accepted' if result is not None else 'rejected' if rejected else 'needs_review'
        if outcome == 'needs_review' and runtime is not None:
            # Retire this uncertain writer before explicit review can release
            # the gate. Its late events cannot prove a subsequent admission.
            desk.retire_runtime(session, runtime)
        with desk.lock:
            if outcome == 'accepted':
                desk.record_admission_mode(session, payload['mode'])
                clear_admitted_draft(desk.store, session, payload)
                _receipt(desk, session, token, outcome, attempt, turn=result)
            else:
                _receipt(desk, session, token, outcome, attempt, error=error)
            return turn_status(desk, session, token)
    finally:
        gate.release()


def resolve_turn(desk, data):
    """Explicit review resolves uncertainty, without ever resending a task."""
    session, token = data['session'], _token(data.get('token'))
    if data.get('outcome') not in ('accepted', 'rejected'):
        raise ValueError('Confirm accepted or rejected task admission')
    gate = desk.admission_lock(session)
    if not gate.acquire(blocking=False):
        raise TurnConflict(turn_status(desk, session, token))
    try:
        with desk.lock:
            intents, receipts = _records(desk, session)
            intent, receipt = intents.get(token), receipts.get(token)
            if intent is None:
                raise ValueError('No saved ordinary task request')
            current = _snapshot(desk, intent, receipt)
            # Our newly acquired gate must not turn an abandoned pending
            # receipt back into a live dispatch.
            status = receipt['status'] if receipt else 'pending'
            if status not in ('pending', 'needs_review'):
                if status == data['outcome']:
                    return current
                raise TurnConflict(current, 'Only unconfirmed admission needs explicit review')
            runtime = desk.runtimes.get(session)
            if data['outcome'] == 'rejected' and runtime is not None:
                if (runtime.process.poll() is None
                        and desk.store.get(session)['status'] in ('starting', 'running', 'approval')):
                    raise TurnConflict(current, 'Finish or stop the proven active native task before rejecting admission')
                desk.retire_runtime(session, runtime)
            if data['outcome'] == 'accepted':
                desk.record_admission_mode(session, intent['payload']['mode'])
                clear_admitted_draft(desk.store, session, intent['payload'])
            _receipt(desk, session, token, data['outcome'], receipt['attempt'] if receipt else 1,
                     reviewed=True)
            return turn_status(desk, session, token)
    finally:
        gate.release()
