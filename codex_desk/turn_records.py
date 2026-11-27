"""Store-only projection of retained ordinary task requests."""
import json

INTENT = 'desk/turnIntent'
RECEIPT = 'desk/turnReceipt'


def request_records(store, session=None, include_archived=False, cwd=None):
    """Read only the two request methods, consistently with caller snapshots."""
    with store.lock:
        if session is not None:
            rows = store.db.execute(
                "SELECT session_id,payload FROM events WHERE session_id=? "
                "AND json_extract(payload,'$.method') IN (?,?) ORDER BY seq",
                (session, INTENT, RECEIPT)).fetchall()
        else:
            rows = store.db.execute(
                "SELECT e.session_id,e.payload FROM events e JOIN sessions s ON s.id=e.session_id "
                "WHERE s.id<>'native-catalog' AND (? OR s.archived=0) "
                "AND (? IS NULL OR recall_cwd(s.cwd)=?) "
                "AND json_extract(e.payload,'$.method') IN (?,?) ORDER BY e.seq",
                (int(include_archived), cwd, cwd, INTENT, RECEIPT)).fetchall()
        result = {}
        for owner, raw in rows:
            event = json.loads(raw)
            params = event['params']
            intents, receipts = result.setdefault(owner, ({}, {}))
            (intents if event['method'] == INTENT else receipts)[params['token']] = params
        return result


def unresolved_requests(store, include_archived=False, cwd=None):
    """Overview identities only; authoritative Review GET owns body and binding."""
    result = {}
    for session, (intents, receipts) in request_records(
            store, include_archived=include_archived, cwd=cwd).items():
        token = next((key for key in reversed(intents)
                      if receipts.get(key, {}).get('status', 'pending')
                      in ('pending', 'needs_review')), None)
        if token is not None:
            intent = intents[token]
            result[session] = {'token': token,
                              'status': receipts.get(token, {}).get('status', 'pending'),
                              'mode': intent['payload']['mode'],
                              'binding': dict(intent['binding'])}
    return result
