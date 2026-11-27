"""Exact selected-turn native diff projection and local clipboard behavior."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
HARNESS = r"""
const assert = require('assert');
const document = {activeElement: null};
class Element {
  constructor(tag = 'div', text = '', cls = '') {
    this.tagName = tag.toUpperCase(); this._text = text; this.className = cls;
    this.children = []; this.dataset = {}; this.parentNode = null;
    this.hidden = false; this.open = false;
    this.disabled = false; this.scrollTop = 0; this.scrollLeft = 0; this.writes = 0;
  }
  get textContent() { return this._text; }
  set textContent(value) {
    this._text = value; this.writes++; this.children = [];
    this.scrollTop = 0; this.scrollLeft = 0;
  }
  set innerHTML(value) { throw new Error('Diff must be rendered as literal text'); }
  append(...nodes) { for (const node of nodes) { node.parentNode = this; this.children.push(node); } }
  remove() {
    if (this.parentNode) {
      const parent = this.parentNode;
      parent.children.splice(parent.children.indexOf(this), 1); this.parentNode = null;
    }
  }
  focus() { document.activeElement = this; }
}
document.body = new Element(); document.activeElement = document.body;
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
};
const ctx = {session: 'desk-a', thread: 'native-parent', generation: 7};
const started = id => ({method: 'turn/started', params: {
  threadId: ctx.thread, turn: {id, status: 'inProgress', items: []}
}});
const updated = (id, diff, extra = {}) => ({method: 'turn/diff/updated', params: {
  threadId: ctx.thread, turnId: id, diff, ...extra
}});
const completed = (id, status) => ({method: 'turn/completed', params: {
  threadId: ctx.thread, turn: {id, status, items: []}
}});
const accept = message => DeskTurnChanges.consume(message, ctx);
const current = () => DeskTurnChanges.state();
const snapshot = turns => ({id: ctx.thread, turns});
const displayed = () => $('turn-changes-body').textContent;
const literal = 'diff --git a/src/保留.js b/src/保留.js\n' +
  '--- a/src/保留.js\n+++ b/src/保留.js\n@@ -1 +1 @@\n' +
  '-const label = "old";\n+const label = "<script>alert(1)</script> & résumé 🚀";\n';
const aggregate = literal + 'diff --git a/tests/保留.txt b/tests/保留.txt\r\n' +
  '--- a/tests/保留.txt\r\n+++ b/tests/保留.txt\r\n@@ -1 +1 @@\r\n' +
  '-old\r\n+new\t<&> "quoted"\r\n\\ No newline at end of file';
const copied = [];
let clipboard = async text => { copied.push(text); };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
global.fetch = () => { throw new Error('Diff review must not send a request'); };
"""

APP_SETUP = r"""
function make(tag, text = '', cls = '') { return new Element(tag, text, cls); }
const DeskSteering={select(){},sync(){},consume(){},restoreThread(){},opened(){},reading:()=>false};
const DeskStopTask={select(){},consume(){},restoreThread(){},sync(){},snapshot:()=>null,opened:async()=>false,reading:()=>false};
let stopStateSnapshot=null;
DeskNativeSteps.configure({$, make}); DeskNativeSteps.select(ctx);
DeskTurnChanges.configure({$, writeText: text => clipboard(text)}); DeskTurnChanges.select(ctx);
let selected = ctx.session, nativeThreadId = ctx.thread, generation = ctx.generation;
let opening = false, after = 0, currentTurn = null, latestUpdates = 0, statePollAt = Date.now();
let isNearLatest = true, followed = 0, labels = 0, refreshes = 0;
const items = new Map(), requests = new Map(), calls = [], frames = [];
let rows = [], state = {sessions: [{id: ctx.session, thread_id: ctx.thread, status: 'running'}]};
const api = async path => { calls.push(path); const result = rows; rows = []; return result; };
const nearLatest = () => isNearLatest;
const requestAnimationFrame = callback => frames.push(callback);
const goLatest = () => { followed++; latestUpdates = 0; };
const latestLabel = () => { labels++; };
const refresh = async () => { refreshes++; };
const turnRequest = () => null;
const drawSidebar = () => {}, syncSelectedOriginal = () => {}, DeskHome = {sync() {}};
const approvals = () => {}, renderItem = () => {};
const setRows = messages => { rows = messages.map((event, index) => ({seq: after + index + 1, event})); };
const flushFrames = () => { while (frames.length) frames.shift()(); };
const plan = id => ({method: 'turn/plan/updated', params: {
  threadId: ctx.thread, turnId: id, explanation: 'Native checklist remains separate',
  plan: [{step: 'Inspect exact changes', status: 'completed'}, {step: 'Run tests', status: 'inProgress'}]
}});
"""


@unittest.skipUnless(NODE, 'Node required')
class TurnChangesControllerTests(unittest.TestCase):
    def check(self, body):
        controller = (ROOT / 'codex_desk/static/turn-changes.js').read_text()
        script = HARNESS + '\n' + controller + """
DeskTurnChanges.configure({$, writeText: text => clipboard(text)});
DeskTurnChanges.select(ctx);
(async () => {
""" + body + "\n})().catch(error => { console.error(error); process.exitCode = 1; });\n"
        result = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_latest_aggregate_replaces_instead_of_appending(self):
        self.check(r"""
assert($('turn-changes').hidden); assert($('turn-changes-copy').disabled);
assert.strictEqual(accept(started('turn-a')), false);
assert(accept(updated('turn-a', literal)));
assert.strictEqual(displayed(), literal);
assert(accept(updated('turn-a', aggregate)));
assert.strictEqual(current().diff, aggregate); assert.strictEqual(displayed(), aggregate);
assert(!$('turn-changes').hidden); assert(!$('turn-changes-copy').disabled);
assert.strictEqual($('turn-changes-summary').textContent, 'Latest reported diff');
assert.strictEqual($('turn-changes-status').textContent, 'Task in progress');
assert.strictEqual($('turn-changes-body').children.length, 0);
const writes = $('turn-changes-body').writes;
assert.strictEqual(accept(updated('turn-a', aggregate)), false);
assert.strictEqual($('turn-changes-body').writes, writes, 'duplicate must not touch reader');
const full = aggregate + '\n' + '+ retained long native line <保留>\n'.repeat(2400);
assert(accept(updated('turn-a', full))); assert.strictEqual(displayed(), full);
await $('turn-changes-copy').onclick(); assert.deepStrictEqual(copied, [full]);
assert.strictEqual($('turn-changes-message').textContent, 'Complete diff copied.');
""")

    def test_quiet_new_turn_and_empty_update_account_only_visible_changes(self):
        self.check(r"""
assert.strictEqual(accept(updated('turn-a', literal)), false, 'diff cannot establish an unknown turn');
assert.strictEqual(accept(started('turn-a')), false);
assert.strictEqual(accept(updated('turn-a', '')), false, 'initial empty native report stays quiet');
assert.strictEqual(current().diff, ''); assert($('turn-changes').hidden);
assert(accept(updated('turn-a', literal))); assert(accept(updated('turn-a', '')));
assert.strictEqual(displayed(), ''); assert($('turn-changes').hidden);
assert($('turn-changes-copy').disabled);
assert.strictEqual(accept(updated('turn-a', '')), false);
assert.strictEqual(accept(started('turn-b')), false);
assert.strictEqual(current().diff, null); assert($('turn-changes').hidden);
assert.strictEqual(accept(updated('turn-a', aggregate)), false);
assert(accept(updated('turn-b', aggregate)));
assert.strictEqual(accept(started('turn-b')), false, 'duplicate started retains current report');
assert.strictEqual(displayed(), aggregate);
assert(accept(started('turn-c')), 'clearing a visible previous report counts once');
assert.strictEqual(current().diff, null); assert.strictEqual(displayed(), '');
assert($('turn-changes').hidden);
assert.strictEqual(accept(started('turn-a')), false, 'retired turn must stay retired');
assert.strictEqual(current().turn, 'turn-c');
assert.strictEqual(accept(completed('turn-c', 'completed')), false, 'quiet completion stays quiet');
assert.strictEqual(accept(updated('turn-c', literal)), false);
""")

    def test_native_terminal_retains_exact_diff_and_retires_late_reports(self):
        self.check(r"""
for (const [index, status] of ['completed', 'interrupted', 'failed'].entries()) {
  const owner = {...ctx, generation: 100 + index}; DeskTurnChanges.select(owner);
  const consume = message => DeskTurnChanges.consume(message, owner);
  consume(started('turn-a')); consume(updated('turn-a', aggregate));
  assert(consume(completed('turn-a', status)));
  assert.strictEqual(current().terminal, status); assert.strictEqual(displayed(), aggregate);
  assert.strictEqual($('turn-changes-status').textContent, 'Task ' + status);
  assert.strictEqual($('turn-changes-summary').textContent, 'Task ' + status);
  assert.strictEqual(consume(completed('turn-a', status)), false);
  assert.strictEqual(consume(completed('turn-a', 'failed')), false);
  assert.strictEqual(consume(updated('turn-a', literal)), false);
  assert.strictEqual(consume(updated('turn-a', '')), false);
  assert.strictEqual(consume(started('turn-a')), false);
  assert.strictEqual(displayed(), aggregate);
  await $('turn-changes-copy').onclick(); assert.strictEqual(copied.at(-1), aggregate);
  assert(consume(started('turn-b'))); assert($('turn-changes').hidden);
  assert.strictEqual(current().terminal, null); assert.strictEqual(current().diff, null);
  assert.strictEqual(consume(completed('turn-a', 'completed')), false);
  assert.strictEqual(consume(updated('turn-a', literal)), false);
  assert(consume(updated('turn-b', literal))); assert.strictEqual(displayed(), literal);
}
""")

    def test_session_process_exit_retains_and_seals_current_report(self):
        self.check(r"""
for (const [index, status] of ['completed', 'interrupted', 'failed'].entries()) {
  const owner = {...ctx, generation: 20 + index}; DeskTurnChanges.select(owner);
  DeskTurnChanges.consume(started('turn-a'), owner);
  DeskTurnChanges.consume(updated('turn-a', aggregate), owner);
  for (const wrong of [
    {id: 'desk-b', thread_id: ctx.thread, status},
    {id: ctx.session, thread_id: 'child', status},
    {id: ctx.session, thread_id: ctx.thread, status: 'running'},
    {id: ctx.session, thread_id: ctx.thread, status: 'approval'},
    {id: ctx.session, thread_id: ctx.thread, status: 'ready'},
  ]) assert.strictEqual(DeskTurnChanges.sync(wrong, owner), false);
  assert.strictEqual(current().terminal, null);
  const session = {id: ctx.session, thread_id: ctx.thread, status};
  assert.strictEqual(DeskTurnChanges.sync(session, {...owner, generation: owner.generation - 1}), false);
  assert(DeskTurnChanges.sync(session, owner));
  assert.strictEqual(current().terminal, status); assert.strictEqual(displayed(), aggregate);
  assert.strictEqual(DeskTurnChanges.sync(session, owner), false);
  assert.strictEqual(DeskTurnChanges.consume(updated('turn-a', literal), owner), false);
}
""")

    def test_owner_parent_thread_turn_generation_and_native_request_isolation(self):
        self.check(r"""
accept(started('turn-a')); accept(updated('turn-a', literal));
const before = JSON.stringify(current()), writes = $('turn-changes-body').writes;
for (const owner of [null, {}, {...ctx, generation: 6}, {...ctx, session: 'desk-b'}, {...ctx, thread: 'child'}]) {
  assert.strictEqual(DeskTurnChanges.consume(started('foreign'), owner), false);
  assert.strictEqual(DeskTurnChanges.consume(updated('turn-a', aggregate), owner), false);
  assert.strictEqual(DeskTurnChanges.sync({id: ctx.session, thread_id: ctx.thread, status: 'failed'}, owner), false);
}
for (const message of [
  {...started('child'), params: {...started('child').params, threadId: 'child'}},
  updated('turn-a', aggregate, {threadId: 'child'}),
  updated('turn-a', aggregate, {threadId: undefined, thread: {id: 'child'}}),
  updated('turn-a', aggregate, {threadId: undefined, turn: {id: 'turn-a', threadId: 'child'}}),
  updated('wrong-turn', aggregate),
  {...updated('turn-a', aggregate), id: 123},
  {...updated('turn-a', aggregate), id: null},
  {method: 'item/fileChange/outputDelta', params: {threadId: ctx.thread, turnId: 'turn-a', delta: aggregate}},
  {method: 'item/completed', params: {threadId: ctx.thread, turnId: 'turn-a', item: {type: 'fileChange', changes: [{diff: aggregate}]}}},
]) assert.strictEqual(accept(message), false);
assert.strictEqual(JSON.stringify(current()), before);
assert.strictEqual($('turn-changes-body').writes, writes);
const ownedWithoutThread = updated('turn-a', aggregate); delete ownedWithoutThread.params.threadId;
assert(accept(ownedWithoutThread), 'retained notifications may rely on selected owner and exact known turn');
assert.strictEqual(displayed(), aggregate);
DeskTurnChanges.select({...ctx, thread: null, generation: 8});
assert.strictEqual(DeskTurnChanges.consume(updated('turn-a', literal), current().context), false);
assert($('turn-changes').hidden);
""")

    def test_malformed_notifications_leave_current_diff_and_terminal_unchanged(self):
        self.check(r"""
accept(started('turn-a')); accept(updated('turn-a', literal));
const before = JSON.stringify(current());
for (const message of [null, {}, {method: 'turn/diff/updated'},
  updated('turn-a', null), updated('turn-a', {}), updated('turn-a', ['not text']),
  updated('turn-a', 1), updated('', aggregate), updated(undefined, aggregate),
  started(''), started(123), completed('turn-a', 'inProgress'),
  completed('turn-a', 'toString'), completed('turn-a', '__proto__')]) {
  assert.strictEqual(accept(message), false);
}
assert.strictEqual(JSON.stringify(current()), before); assert.strictEqual(displayed(), literal);
""")

    def test_ordered_replay_and_same_owner_cold_return_restore_latest_exact_diff(self):
        self.check(r"""
const events = [
  started('old'), updated('old', literal), updated('old', aggregate),
  completed('old', 'completed'), updated('old', 'late old overwrite'),
  started('new'), updated('new', literal), updated('new', ''), updated('new', aggregate),
  completed('new', 'interrupted'), updated('new', 'late new overwrite'), started('old'),
];
for (const event of events) accept(event);
const before = current(); assert.strictEqual(before.turn, 'new');
DeskTurnChanges.select({session: 'desk-b', thread: 'other-parent', generation: 8});
assert($('turn-changes').hidden);
for (const event of events) assert.strictEqual(accept(event), false);
const coldOwner = {...ctx, generation: 9}; DeskTurnChanges.select(coldOwner);
for (const event of events) DeskTurnChanges.consume(event, coldOwner);
assert.strictEqual(current().turn, before.turn); assert.strictEqual(current().terminal, before.terminal);
assert.strictEqual(current().diff, before.diff); assert.strictEqual(displayed(), aggregate);
assert(!$('turn-changes').open, 'new selection does not reopen retained reader automatically');
assert.strictEqual(copied.length, 0, 'replay does not copy or send work');
""")

    def test_newer_snapshot_advances_but_older_foreign_and_retired_snapshot_cannot_replace_stream(self):
        self.check(r"""
accept(started('old')); accept(updated('old', literal));
DeskTurnChanges.restoreThread(snapshot([
  {id: 'old', status: 'completed'}, {id: 'snapshot-new', status: 'inProgress'},
]), ctx);
assert.strictEqual(current().turn, 'snapshot-new'); assert.strictEqual(current().diff, null);
assert($('turn-changes').hidden);
accept(updated('snapshot-new', aggregate)); accept(started('stream-new')); accept(updated('stream-new', literal));
const before = JSON.stringify(current());
for (const owner of [ctx, {...ctx, generation: 6}, {...ctx, session: 'desk-b'}]) {
  DeskTurnChanges.restoreThread(snapshot([
    {id: 'old', status: 'completed'}, {id: 'snapshot-new', status: 'completed'},
  ]), owner);
}
DeskTurnChanges.restoreThread({id: 'child', turns: [{id: 'other', status: 'completed'}]}, ctx);
DeskTurnChanges.restoreThread(snapshot([{id: 'stream-new', status: 'inProgress'}, {id: 'old', status: 'completed'}]), ctx);
assert.strictEqual(JSON.stringify(current()), before);
assert.strictEqual(displayed(), literal);
DeskTurnChanges.restoreThread(snapshot([{id: 'stream-new', status: 'completed'}]), ctx);
assert.strictEqual(current().terminal, 'completed'); assert.strictEqual(displayed(), literal);
assert.strictEqual(accept(updated('stream-new', aggregate)), false);
""")

    def test_snapshot_without_retained_aggregate_stays_quiet_and_scope_is_copied(self):
        self.check(r"""
DeskTurnChanges.restoreThread(snapshot([{id: 'snapshot-only', status: 'inProgress', items: [
  {type: 'fileChange', changes: [{diff: literal}]},
]}]), ctx);
assert.strictEqual(current().turn, 'snapshot-only'); assert.strictEqual(current().diff, null);
assert($('turn-changes').hidden, 'individual file changes are not an aggregated turn report');
assert(accept(updated('snapshot-only', aggregate)));
const returned = current(); returned.context.session = 'mutated'; returned.context.generation = 1000;
assert.deepStrictEqual(current().context, ctx);
const message = updated('snapshot-only', literal); assert(accept(message)); message.params.diff = 'mutated payload';
assert.strictEqual(displayed(), literal);
DeskTurnChanges.select({...ctx}); assert.strictEqual(displayed(), literal);
""")

    def test_updates_preserve_disclosure_keyboard_focus_and_reader_scroll(self):
        self.check(r"""
accept(started('turn-a')); accept(updated('turn-a', literal));
const disclosure = $('turn-changes'), body = $('turn-changes-body'), copy = $('turn-changes-copy');
disclosure.open = true; body.focus(); body.scrollTop = 170; body.scrollLeft = 29;
assert(accept(updated('turn-a', aggregate)));
assert.strictEqual($('turn-changes'), disclosure); assert.strictEqual($('turn-changes-body'), body);
assert.strictEqual($('turn-changes-copy'), copy); assert(disclosure.open);
assert.strictEqual(document.activeElement, body); assert.strictEqual(body.scrollTop, 170); assert.strictEqual(body.scrollLeft, 29);
copy.focus(); assert(accept(updated('turn-a', literal)));
assert.strictEqual(document.activeElement, copy); assert(disclosure.open);
assert.strictEqual(body.scrollTop, 170); assert.strictEqual(body.scrollLeft, 29);
assert(accept(completed('turn-a', 'failed'))); assert.strictEqual(document.activeElement, copy);
assert(disclosure.open); assert.strictEqual(body.scrollTop, 170);
DeskTurnChanges.select({...ctx}); assert(disclosure.open); assert.strictEqual(displayed(), literal);
DeskTurnChanges.select({...ctx, generation: 8});
assert(disclosure.hidden); assert(!disclosure.open); assert.strictEqual(body.scrollTop, 0); assert.strictEqual(body.scrollLeft, 0);
""")

    def test_copy_failure_is_local_retryable_and_does_not_change_report(self):
        self.check(r"""
accept(started('turn-a')); accept(updated('turn-a', aggregate));
const before = JSON.stringify(current());
clipboard = async text => { copied.push(text); throw new Error('Clipboard denied'); };
await $('turn-changes-copy').onclick();
assert.strictEqual($('turn-changes-message').textContent, 'Copy failed: Clipboard denied');
assert(!$('turn-changes-copy').disabled); assert.strictEqual(JSON.stringify(current()), before);
clipboard = async text => { copied.push(text); };
await $('turn-changes-copy').onclick();
assert.strictEqual($('turn-changes-message').textContent, 'Complete diff copied.');
assert.deepStrictEqual(copied, [aggregate, aggregate]); assert.strictEqual(JSON.stringify(current()), before);
assert(accept(updated('turn-a', literal))); assert.strictEqual($('turn-changes-message').textContent, '');
""")

    def test_pending_copy_captures_immutable_display_and_does_not_label_newer_diff(self):
        self.check(r"""
accept(started('turn-a')); accept(updated('turn-a', literal));
const held = deferred(); clipboard = text => { copied.push(text); return held.promise; };
const pending = $('turn-changes-copy').onclick();
assert.strictEqual($('turn-changes-message').textContent, 'Copying diff…');
assert(accept(updated('turn-a', aggregate))); assert.strictEqual($('turn-changes-message').textContent, '');
held.resolve(); await pending;
assert.deepStrictEqual(copied, [literal]); assert.strictEqual(displayed(), aggregate);
assert.strictEqual($('turn-changes-message').textContent, '', 'old completion must not label newer display');
const failed = deferred(); clipboard = text => { copied.push(text); return failed.promise; };
const failing = $('turn-changes-copy').onclick();
assert(accept(updated('turn-a', literal))); failed.reject(new Error('old failure')); await failing;
assert.strictEqual($('turn-changes-message').textContent, ''); assert.strictEqual(displayed(), literal);
""")

    def test_copy_races_across_selection_generation_and_turn_remain_local(self):
        self.check(r"""
for (const [index, change] of ['generation', 'session', 'turn', 'empty'].entries()) {
  const owner = {...ctx, generation: 30 + index}; DeskTurnChanges.select(owner);
  const consume = event => DeskTurnChanges.consume(event, owner);
  consume(started('turn-a')); consume(updated('turn-a', aggregate));
  const held = deferred(); clipboard = text => { copied.push(text); return held.promise; };
  const pending = $('turn-changes-copy').onclick();
  if (change === 'generation') DeskTurnChanges.select({...owner, generation: owner.generation + 1});
  if (change === 'session') DeskTurnChanges.select({...owner, session: 'desk-b'});
  if (change === 'turn') consume(started('turn-b'));
  if (change === 'empty') consume(updated('turn-a', ''));
  held.resolve(); await pending;
  assert.strictEqual($('turn-changes-message').textContent, ''); assert.strictEqual(displayed(), '');
  assert.strictEqual(copied.at(-1), aggregate);
  const count = copied.length; await $('turn-changes-copy').onclick();
  assert.strictEqual(copied.length, count, 'hidden empty reports cannot copy');
}
""")

    def test_latest_copy_attempt_owns_feedback_and_terminal_copy_can_finish(self):
        self.check(r"""
accept(started('turn-a')); accept(updated('turn-a', aggregate));
const first = deferred(), second = deferred(); let calls = 0;
clipboard = text => { copied.push(text); return (++calls === 1 ? first : second).promise; };
const older = $('turn-changes-copy').onclick(), newer = $('turn-changes-copy').onclick();
second.resolve(); await newer;
assert.strictEqual($('turn-changes-message').textContent, 'Complete diff copied.');
first.reject(new Error('older copy failure')); await older;
assert.strictEqual($('turn-changes-message').textContent, 'Complete diff copied.');
const terminalCopy = deferred(); clipboard = text => terminalCopy.promise;
const pending = $('turn-changes-copy').onclick(); accept(completed('turn-a', 'completed'));
terminalCopy.resolve(); await pending;
assert.strictEqual($('turn-changes-message').textContent, 'Complete diff copied.');
assert.strictEqual(current().terminal, 'completed'); assert.strictEqual(displayed(), aggregate);
""")


@unittest.skipUnless(NODE, 'Node required')
class TurnChangesAppProjectionTests(unittest.TestCase):
    def check(self, body):
        static = ROOT / 'codex_desk/static'
        source = (static / 'app.js').read_text()
        consume = source[source.index('function consume(m)'):source.index('async function refresh()')]
        poll = source[source.index('async function pollActivity()'):source.index('async function tick()')]
        draw_sync = source[source.index('function draw()'):source.index("  $('archive-session').hidden=false;")] + '}\n'
        script = (HARNESS + '\n' + (static / 'native-steps.js').read_text() + '\n'
                  + (static / 'turn-changes.js').read_text() + '\n' + APP_SETUP + '\n'
                  + consume + poll + draw_sync + '\n(async () => {\n' + body
                  + '\n})().catch(error => { console.error(error); process.exitCode = 1; });\n')
        result = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_diff_updates_count_once_without_changing_native_steps(self):
        self.check(r"""
consume(started('turn-a')); consume(plan('turn-a'));
consume(updated('turn-a', 'Initial reported diff'));
const checklist = JSON.stringify(DeskNativeSteps.state().reported);
$('turn-changes').open = true;
setRows([updated('turn-a', literal), updated('turn-a', aggregate), updated('turn-a', aggregate),
  updated('turn-a', 'child', {threadId: 'child'}), updated('wrong-turn', 'wrong')]);
await pollActivity();
assert.strictEqual(displayed(), aggregate); assert.strictEqual(latestUpdates, 2);
assert.strictEqual(followed, 0); assert.strictEqual(frames.length, 0);
assert.strictEqual(JSON.stringify(DeskNativeSteps.state().reported), checklist);
await $('turn-changes-copy').onclick(); assert.strictEqual(latestUpdates, 2);
setRows([completed('turn-a', 'interrupted'), updated('turn-a', 'late'), updated('turn-a', '')]);
await pollActivity(); assert.strictEqual(latestUpdates, 3, 'one terminal event counts once for both visible readouts');
assert.strictEqual(displayed(), aggregate); assert.strictEqual(JSON.stringify(DeskNativeSteps.state().reported), checklist);
setRows([started('turn-b'), updated('turn-b', literal)]); await pollActivity();
assert.strictEqual(latestUpdates, 5); assert.strictEqual(displayed(), literal);
assert.strictEqual(DeskNativeSteps.state().reported, null);
assert(calls.every(path => path.startsWith('/api/events?')), 'readout only uses the existing events poll');
""")

    def test_expanded_or_new_generation_late_latest_frame_never_follows(self):
        self.check(r"""
consume(started('turn-a')); setRows([updated('turn-a', literal)]); await pollActivity();
assert.strictEqual(frames.length, 1); assert.strictEqual(followed, 0);
$('turn-changes').open = true; flushFrames();
assert.strictEqual(followed, 0); assert.strictEqual(latestUpdates, 1);
$('turn-changes').open = false; setRows([updated('turn-a', aggregate)]); await pollActivity();
assert.strictEqual(frames.length, 1); generation++; flushFrames();
assert.strictEqual(followed, 0); assert.strictEqual(latestUpdates, 1);
generation = ctx.generation; isNearLatest = false; setRows([updated('turn-a', literal)]); await pollActivity();
assert.strictEqual(frames.length, 0); assert.strictEqual(latestUpdates, 2); assert.strictEqual(followed, 0);
""")

    def test_state_only_terminal_sync_counts_once_and_does_not_scroll_or_rewrite_diff(self):
        self.check(r"""
consume(started('turn-a')); consume(updated('turn-a', aggregate)); consume(plan('turn-a'));
const checklist = JSON.stringify(DeskNativeSteps.state().reported), before = displayed();
state.sessions[0].status = 'failed'; opening = true; draw();
assert.strictEqual(current().terminal, null); assert.strictEqual(latestUpdates, 0);
opening = false; draw();
assert.strictEqual(current().terminal, 'failed'); assert.strictEqual(DeskNativeSteps.state().terminal, 'failed');
assert.strictEqual(latestUpdates, 1); assert.strictEqual(labels, 1); assert.strictEqual(followed, 0);
assert.strictEqual(displayed(), before); assert.strictEqual(JSON.stringify(DeskNativeSteps.state().reported), checklist);
draw(); assert.strictEqual(latestUpdates, 1); assert.strictEqual(labels, 1);
assert.strictEqual(consume(updated('turn-a', literal)), false);
const next = {...ctx, generation: 8}; generation = 8; state.sessions[0].status = 'running';
DeskNativeSteps.select(next); DeskTurnChanges.select(next); consume(started('quiet'));
state.sessions[0].status = 'interrupted'; draw();
assert.strictEqual(current().terminal, 'interrupted'); assert.strictEqual(latestUpdates, 1, 'quiet terminal sync has no visible update');
assert.strictEqual(calls.length, 0, 'state projection sends no request');
""")

    def test_hidden_open_readers_after_new_turn_or_empty_report_allow_latest_follow(self):
        self.check(r"""
consume(started('turn-a')); consume(plan('turn-a')); consume(updated('turn-a', literal));
$('native-steps').open = true; $('turn-changes').open = true;
consume(started('turn-b'));
for (const id of ['native-steps', 'turn-changes']) {
  assert($(id).hidden); assert($(id).open, 'new turn preserves the parked disclosure preference');
}
const output = text => ({method: 'item/agentMessage/delta', params: {
  threadId: ctx.thread, turnId: 'turn-b', itemId: 'answer', delta: text
}});
setRows([output('Quiet new turn output')]); await pollActivity();
assert.strictEqual(frames.length, 1, 'hidden parked readers cannot pause near-latest follow');
flushFrames(); assert.strictEqual(followed, 1); assert.strictEqual(latestUpdates, 0);
consume(plan('turn-b')); consume(updated('turn-b', aggregate));
setRows([output('Visible expanded review keeps its reading position')]); await pollActivity();
assert.strictEqual(frames.length, 0); assert.strictEqual(followed, 1); assert.strictEqual(latestUpdates, 1);
consume({...plan('turn-b'), params: {...plan('turn-b').params, plan: []}});
consume(updated('turn-b', ''));
for (const id of ['native-steps', 'turn-changes']) { assert($(id).hidden); assert($(id).open); }
setRows([output('Empty reports no longer pause output')]); await pollActivity();
assert.strictEqual(frames.length, 1); flushFrames();
assert.strictEqual(followed, 2); assert.strictEqual(latestUpdates, 0);
""")

    def test_hidden_open_reader_reappearing_before_latest_frame_blocks_follow(self):
        self.check(r"""
consume(started('turn-a')); consume(updated('turn-a', literal));
$('turn-changes').open = true; consume(updated('turn-a', ''));
assert($('turn-changes').hidden); assert($('turn-changes').open);
const output = text => ({method: 'item/agentMessage/delta', params: {
  threadId: ctx.thread, turnId: 'turn-a', itemId: 'answer', delta: text
}});
setRows([output('Output before reappearing diff')]); await pollActivity();
assert.strictEqual(frames.length, 1);
consume(updated('turn-a', aggregate));
assert(!$('turn-changes').hidden); assert($('turn-changes').open);
flushFrames(); assert.strictEqual(followed, 0); assert.strictEqual(latestUpdates, 1);
consume(updated('turn-a', ''));
setRows([output('Output before reappearing steps')]); await pollActivity();
assert.strictEqual(frames.length, 1);
consume(plan('turn-a')); $('native-steps').open = true;
flushFrames(); assert.strictEqual(followed, 0); assert.strictEqual(latestUpdates, 2);
consume({...plan('turn-a'), params: {...plan('turn-a').params, plan: []}});
assert($('native-steps').hidden); assert($('native-steps').open);
setRows([output('Both parked readers are hidden again')]); await pollActivity();
assert.strictEqual(frames.length, 1); flushFrames();
assert.strictEqual(followed, 1); assert.strictEqual(latestUpdates, 0);
""")


if __name__ == '__main__':
    unittest.main()
