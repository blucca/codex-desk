"""One reviewed Handoff target, retained through explicit retry and admission review.

Uses the existing private Store event and follow-up admission receipts.
"""
import os
from pathlib import Path
import uuid
from .followups import add_followup, followup_snapshot, MAX_FOLLOWUP_CHARS

_INTENT='desk/handoffIntent'
_RECEIPT='desk/handoffReceipt'

class HandoffConflict(ValueError):
    def __init__(self,current):
        self.current=current
        super().__init__('This request belongs to different reviewed work. Use a new request for a changed task or scope.')

def _target(token):
    if not isinstance(token,str):raise ValueError('Use the reviewed handoff request ID')
    try:value=uuid.UUID(token)
    except (ValueError,AttributeError):raise ValueError('Use the reviewed handoff request ID') from None
    if str(value)!=token:raise ValueError('Use the reviewed handoff request ID')
    return 'handoff-'+value.hex

def _home(desk):return os.path.normcase(str(Path(desk.home).expanduser().resolve()))

def _identity(desk,data):
    values={}
    for key in ('source','cwd','profile','goal','text'):
        value=data.get(key)
        if not isinstance(value,str) or not value.strip():raise ValueError('Review the handoff '+key+' before starting')
        values[key]=value.strip() if key in ('goal','text') else value
    values['cwd']=str(Path(values['cwd']).expanduser().resolve(strict=False))
    values['native_home']=_home(desk)
    prepared='Next task: '+values['goal']+'\n\n'+values['text']
    if len(prepared)>MAX_FOLLOWUP_CHARS:raise ValueError('The reviewed handoff exceeds the prepared task text limit')
    return values,prepared

def _records(desk,identifier):
    records=desk.store.events(identifier)
    intent=next((r['event']['params'] for r in records if r['event'].get('method')==_INTENT),None)
    receipt=next((r['event']['params'] for r in reversed(records) if r['event'].get('method')==_RECEIPT),None)
    return intent,receipt

def _validate_home(desk,intent):
    if intent and intent['identity']['native_home']!=_home(desk):
        raise ValueError('Reopen the original Codex home to review this handoff request')

def validate_handoff_home(desk,identifier):
    """A retained target's native home also governs explicit open/Send next."""
    if not isinstance(identifier,str) or not identifier.startswith('handoff-'):return
    intent,_=_records(desk,identifier)
    _validate_home(desk,intent)

def record_handoff_admission(desk,identifier,reservation,admission=None,turn=None,error=None):
    """Project only the original captured follow-up's authoritative receipt.

    The same target's later edited revisions and other tasks do not establish
    admission of the original reviewed Handoff body.
    """
    if not identifier.startswith('handoff-'):return
    with desk.lock:
        intent,current=_records(desk,identifier)
        if not intent or not current:return
        identity=intent['identity']
        if (reservation['entry_id']!=current['entry_id']
                or reservation['revision']!=current.get('revision',1)
                or reservation['text']!='Next task: '+identity['goal']+'\n\n'+identity['text']
                or reservation['mode']!='native'):return
        state={'status':'pending','entry_id':reservation['entry_id'],'revision':reservation['revision'],
               'reservation_token':reservation['token']}
        if admission is not None:
            state.update(status='accepted' if admission['outcome']=='accepted' else 'needs_review',admission=admission)
            if turn is not None:state['turn']=turn
            if error is not None and admission['outcome']!='accepted':state['error']=error
        desk.store.event(identifier,{'method':_RECEIPT,'params':state})

def handoff_status(desk,token):
    """Recover an existing request without opening/resuming or dispatching it."""
    identifier=_target(token)
    with desk.lock:
        if desk.store.get(identifier) is None:return None
        intent,receipt=_records(desk,identifier)
        _validate_home(desk,intent)
        state=receipt or {'status':'pending','entry_id':intent.get('entry_id') if intent else None}
        active=(identifier in getattr(desk,'handoff_dispatching',set())
                or identifier in getattr(desk,'followup_sends',{}))
        if not intent or (state['status']=='pending' and not active):
            state={**state,'status':'needs_review','error':'No completed admission receipt. Review the retained target and preparation.'}
        return {'id':identifier,'token':token,'handoff':state,
                'preparation':followup_snapshot(desk.store,identifier)}

def start_handoff(desk,data):
    """Only first creation dispatches. Every duplicate recovers the same target."""
    token=data.get('token');identifier=_target(token);identity,prepared=_identity(desk,data)
    with desk.lock:
        existing=handoff_status(desk,token)
        if existing is not None:
            intent,_=_records(desk,identifier)
            if not intent or intent['identity']!=identity:raise HandoffConflict(existing)
            return existing
        # Validate native project/profile before any private target is created.
        cwd=str(desk.project_path(identity['cwd']));profile=desk.profile_id(identity['profile'])
        desk.store.create(cwd,profile,identifier=identifier)
        # The intent precedes native work. A stopped process can only recover,
        # never infer that its previously pending task should be replayed.
        desk.store.event(identifier,{'method':_INTENT,'params':{'identity':identity}})
        entry=add_followup(desk.store,identifier,prepared,'native')
        desk.store.event(identifier,{'method':_RECEIPT,'params':{'status':'pending','entry_id':entry['id'],'revision':entry['revision']}})
        if not hasattr(desk,'handoff_dispatching'):desk.handoff_dispatching=set()
        desk.handoff_dispatching.add(identifier)
    try:
        result=desk.send_followup({'session':identifier,'id':entry['id'],'revision':entry['revision']})
        receipt={'status':'accepted','entry_id':entry['id'],'admission':result['receipt'],'turn':result.get('turn')}
    except Exception as error:
        # Existing exact follow-up admission determines rejected/unknown state.
        snapshot=getattr(error,'snapshot',None)
        receipt={'status':'needs_review','entry_id':entry['id'],'error':str(error)}
        if snapshot and snapshot.get('receipt'):receipt['admission']=snapshot['receipt']
    try:
        with desk.lock:
            # send/resolve own the exact receipt. A later explicit retry can
            # finish before this first caller returns; never overwrite it.
            _,current=_records(desk,identifier)
            if current['status']=='pending' and 'reservation_token' not in current:
                desk.store.event(identifier,{'method':_RECEIPT,'params':{**receipt,'revision':entry['revision']}})
    finally:
        with desk.lock:desk.handoff_dispatching.discard(identifier)
    return handoff_status(desk,token)
