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


def unresolved_request_query(scoped, include_archived):
    """SQL corpus for the same current gate as unresolved_requests.

    UUID discovery follows first intent insertion order; a later attachment
    updates that UUID's captured binding/body without making it a new request.
    Methods are selected inside SQLite before any native activity is returned.
    """
    sql = """WITH request_events AS (
        SELECT e.session_id,e.seq,e.payload,json_extract(e.payload,'$.method') method,
            json_extract(e.payload,'$.params.token') token
        FROM events e JOIN sessions s ON s.id=e.session_id
        WHERE s.id<>'native-catalog' AND (? OR s.archived=0)
        AND (? IS NULL OR recall_cwd(s.cwd)=?)
        AND json_extract(e.payload,'$.method') IN (?,?)
    ), intents AS (
        SELECT session_id,token,min(seq) first_seq,max(seq) seq
        FROM request_events WHERE method=? GROUP BY session_id,token
    ), receipts AS (
        SELECT session_id,token,max(seq) seq
        FROM request_events WHERE method=? GROUP BY session_id,token
    ), retained AS (
        SELECT i.session_id,i.token,i.first_seq,e.payload,
            CASE WHEN json_type(r.payload,'$.params.status') IS NULL THEN 'pending'
                ELSE json_extract(r.payload,'$.params.status') END status
        FROM intents i JOIN request_events e ON e.seq=i.seq
        LEFT JOIN receipts latest ON latest.session_id=i.session_id AND latest.token=i.token
        LEFT JOIN request_events r ON r.seq=latest.seq
    ), unresolved AS (
        SELECT * FROM retained WHERE status IN ('pending','needs_review')
    )
    SELECT u.session_id,u.token,u.status,json_extract(u.payload,'$.params.payload.mode') mode,
        json_extract(u.payload,'$.params.payload.text') text
    FROM unresolved u WHERE NOT EXISTS (
        SELECT 1 FROM unresolved later WHERE later.session_id=u.session_id
        AND later.first_seq>u.first_seq)
    """
    return sql, (int(include_archived), scoped, scoped, INTENT, RECEIPT, INTENT, RECEIPT)
