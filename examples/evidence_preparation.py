#!/usr/bin/env python3
"""Reproduce exact evidence preparation with synthetic source/turn transport.

Runs the product draft, Prepared snapshot, queue and retained Run-request domain
against temporary SQLite state. The supplied turn transport reports unknown
admission so the same captured instruction can be reviewed after a cold reopen.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import uuid

from codex_desk.drafts import load_draft, save_draft
from codex_desk.evidence_reference import (
    append_evidence_block, capture_reference, format_evidence_block,
    parse_evidence_blocks, resolve_reference,
)
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.preparation import preparation_snapshot
from codex_desk.runtime import NativeRequestUnknown
from codex_desk.server import Desk
from codex_desk.turn_dispatch import resolve_turn, start_turn, turn_status


QUOTE = 'Retry budget: café\u0301🙂 — 2 attempts.'


def reader_text(item):
    """The history-reader-text/v1 projection for this agentMessage fixture."""
    assert item['type'] == 'agentMessage'
    return 'Codex\n' + item['text']


def run(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='evidence-preparation-') as scratch:
        folder = Path(scratch)
        home, state = folder / 'native-home', folder / 'state'
        home.mkdir()
        project = folder / 'project-B'; project.mkdir()
        removed = folder / 'project-A'; removed.mkdir(); removed.rmdir()
        source = {'id': 'native-source-A', 'name': 'Checkout retry decision',
                  'cwd': str(removed), 'turns': [{'id': 'source-turn', 'status': 'failed',
                  'items': [{'id': 'source-item', 'type': 'agentMessage', 'phase': 'commentary',
                             'text': 'Before🙂 ' + QUOTE + '\nLater decision: ' + QUOTE + '\nAfter'}]}]}
        original = copy.deepcopy(source)
        desk = Desk('fixture-not-executed', home, state)
        cold = None
        try:
            session = desk.store.create(str(project), 'default', identifier='local-B', name='Unsent checkout Plan')
            desk.store.update(session, thread_id='native-destination-B', status='saved', mode='plan')
            existing = save_draft(desk.store, session, 'Inspect the retry budget before the next edit.  \n  ',
                                  'plan', 0, 'example-page', 1)
            add_followup(desk.store, session, 'First independent Work instruction.', 'native')
            add_followup(desk.store, session, 'Second independent Plan instruction.', 'plan')
            queues_before = followup_snapshot(desk.store, session)

            text = reader_text(source['turns'][0]['items'][0])
            start = text.rfind(QUOTE)  # The later of two identical occurrences.
            reference = capture_reference(source, native_home=desk.native_home_namespace(),
                thread_id='native-source-A', turn_id='source-turn', item_id='source-item',
                quote_start=start, quote_end=start + len(QUOTE), expected_quote=QUOTE,
                text_for_item=reader_text)
            block = format_evidence_block(reference)
            prepared_text = append_evidence_block(existing['text'], block)
            saved = save_draft(desk.store, session, prepared_text, existing['mode'],
                               existing['revision'], 'example-page', 2)
            prepared = preparation_snapshot(desk.store)['sessions'][0]
            assert prepared['draft'] == saved
            assert prepared['followups'] == queues_before
            assert desk.store.get('native-source-A') is None and source == original

            queued = add_followup(desk.store, session, prepared_text, 'plan')
            queues = followup_snapshot(desk.store, session)
            assert queues['entries'][:2] == queues_before['entries']
            assert queued['text'] == saved['text'] and queues['reservation'] is None

            calls = []

            class SuppliedTurnTransport:
                def turn(self, instruction, mode):
                    calls.append({'text': instruction, 'mode': mode})
                    raise NativeRequestUnknown('Synthetic lost admission reply')

                def close(self):
                    pass

            request = {'session': session, 'token': str(uuid.uuid4()), 'text': saved['text'],
                       'mode': saved['mode'], 'revision': saved['revision'],
                       'writer': 'example-page', 'sequence': 2}
            with patch.object(desk, 'runtime', return_value=SuppliedTurnTransport()):
                receipt = start_turn(desk, request)
            assert receipt['request']['status'] == 'needs_review'
            assert calls == [{'text': prepared_text, 'mode': 'plan'}]
            newer = save_draft(desk.store, session, prepared_text + '\nSeparate newer next-step note.',
                               'native', saved['revision'], 'example-page', 3)
            desk.close(); desk.store.db.close()
            desk = None

            cold = Desk('fixture-not-executed', home, state)
            before = list(cold.store.db.iterdump())
            retained = turn_status(cold, session, request['token'])
            assert retained['request']['payload']['text'] == prepared_text
            parsed = parse_evidence_blocks(retained['request']['payload']['text'])
            assert len(parsed) == 1 and parsed[0]['reference'] == reference
            assert list(cold.store.db.iterdump()) == before
            assert followup_snapshot(cold.store, session) == queues
            resolved_request = resolve_turn(cold, {'session': session, 'token': request['token'],
                                                   'outcome': 'rejected'})
            assert resolved_request['request']['status'] == 'rejected'
            assert load_draft(cold.store, session) == newer
            assert followup_snapshot(cold.store, session) == queues

            available = resolve_reference(reference, cold.native_home_namespace(), source,
                                          text_for_item=reader_text)
            assert available['available'] and available['quote_start'] == start
            changed = copy.deepcopy(source)
            item = changed['turns'][0]['items'][0]
            item['text'] = item['text'].replace('Later decision: ' + QUOTE,
                                               'Later decision: X' + QUOTE[1:])
            changed_result = resolve_reference(reference, cold.native_home_namespace(), changed,
                                               text_for_item=reader_text)
            missing = copy.deepcopy(source); missing['turns'][0]['items'] = []
            missing_result = resolve_reference(reference, cold.native_home_namespace(), missing,
                                               text_for_item=reader_text)
            other_home = resolve_reference(reference, '0' * 64, source, text_for_item=reader_text)
            assert changed_result['status'] == 'quote_changed'
            assert missing_result['status'] == 'source_unavailable'
            assert other_home['status'] == 'home_mismatch'
            assert parse_evidence_blocks(newer['text'])[0]['reference']['quote'] == QUOTE
            assert source == original and not removed.exists()

            return {'passed': True, 'source_thread': reference['thread_id'],
                    'destination_thread': 'native-destination-B', 'projection': reference['projection'],
                    'offset_unit': reference['offset_unit'], 'quote': reference['quote'],
                    'selected_occurrence': 2, 'source_folder_removed': True,
                    'existing_plan_preserved': True, 'original_two_queues_preserved': True,
                    'retained_request_survived_cold_reopen': True,
                    'newer_draft_survived_request_resolution': True,
                    'exact_return': available['status'], 'changed_return': changed_result['status'],
                    'missing_return': missing_result['status'], 'other_home_return': other_home['status'],
                    'supplied_turn_transport_calls': len(calls)}
        finally:
            for owner in (desk, cold):
                if owner is not None:
                    owner.close(); owner.store.db.close()


if __name__ == '__main__':
    temporary_root = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
    print(json.dumps(run(temporary_root), indent=2, ensure_ascii=False))
