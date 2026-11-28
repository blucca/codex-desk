# Bring one original excerpt into an unsent task

Keep **B**, the task you are preparing, selected. Read a saved Codex conversation
**A**, review one excerpt, and append it to B's existing draft. Later, return from
that saved preparation to the exact turn, item and occurrence in A.

## Read A without leaving B

1. Write B's next task, choose **Work** or **Plan**, and wait for **Draft saved locally**.
2. Use **Recent work**, title browsing or saved-content search to find A. Choose
   **Read original conversation**. With a known native thread ID, use **Browse all
   conversations** → **Native conversation ID** → **Read original by ID** instead.
   [ID → instruction → own response → B quote/return](find-original-by-id-or-instruction.md).
3. Find the relevant answer, command result or tool evidence. **Find in this
   original conversation** searches the full supplied item text, including later
   text windows. Use **Next match** when the same words occur more than once.
4. Select the exact excerpt and choose **Review evidence for task**. For a short item,
   reviewing without a selection captures the whole item. A long item requires
   a selection of at most 8,000 Unicode characters.

A's saved project folder can be gone: reading and quoting its original evidence
use its native history. B's selected conversation, unsent text, mode and queued
instructions remain in place.

## Review, then append locally

The review shows B's current unsent draft beside A's exact excerpt and captured
source identity. Check the thread, turn, item, source kind, reported phase/status
and project folder. Command evidence also shows supplied command/exit facts.
Add a **Separate next-step note** if needed; the note stays separate from the
original quote.

Choose **Append to draft**. B keeps its existing text and Work/Plan mode, followed
by the reviewed note and evidence block. The normal local draft save owns the
revision. **Return without appending** restores the source reading view instead.
If the draft changed while you were reviewing, return and review its current
text. Use the ordinary **Keep mine** or **Load saved draft** controls for a save
conflict.

The block is readable text with an embedded source reference. It carries the
opaque native-home namespace, exact native IDs, reader projection and literal
Unicode code-point span. Repeated phrases, emoji and combining characters keep
their selected occurrence. The reported phase/status remains the one you reviewed.

## Return to the exact original

Expand **Referenced originals in this draft** and choose **Read referenced original**. Desk reads A
again in the captured native home, compares the same item's same span, and opens
the matching text window. The reader shows the **saved reviewed excerpt**
separately from the fresh original. Return to the prepared task to recover its
editor selection, scroll position and mode.

If the source changed, its item disappeared, or that home is unavailable, the
saved quote stays in your preparation. An equal phrase elsewhere is not selected
as a replacement. **Retry read** reads the same captured source again. Relaunch
with the original `--codex-home` to read evidence from another native home.

Reuse the same `--state-dir` when restarting Desk. The saved evidence remains in
the draft; reopening the page restores preparation before you explicitly read A.

### Keep a quoted command result through completion

Select an excerpt wholly inside the command's reported output. New evidence blocks
use `history-reader-command-output/v1`: the literal Unicode span is relative to
that native item's output, rather than its changing Status/Exit header. Completing
the command or appending later output keeps the exact saved quote addressable.
The block retains the status you originally reviewed; the fresh reader shows the
current native item. Reopening and Refresh preserve the same output occurrence.

Header or header-plus-output selections, and existing `history-reader-text/v1`
blocks, keep their original literal full-item spans. If the quoted output changes
at its captured output offset, the saved excerpt stays in your preparation and
no other occurrence replaces it.

### Keep supplied tool-result evidence through native status updates

Output-only quotes from supplied MCP or dynamic-tool results use
`history-reader-tool-result/v1`. Their Unicode span is relative to the reader's
exact readable result projection. Native Status/duration/success or Arguments
updates keep the same result quote addressable; the saved block retains the
reported state you reviewed. The fresh reader shows the current native state.

Selections in Arguments, headers, Error or Progress, and selections across a
result boundary, retain literal full-item spans. Existing evidence blocks keep
their original projection. A changed quoted result at the captured result offset
is reported without substituting another occurrence. The result projection uses
the reader's existing text/media/resource representation.

## Read the task behind an excerpt

In A's original reader, choose **Read containing task** beside the answer, command
result or tool evidence you are inspecting. The task context identifies that
item's own native turn, its reported status/error and each user instruction
supplied in that turn.

1. Choose **Read full instruction** to read the exact user-message item with the
   ordinary full-text windows, Find and Copy controls.
2. Choose **Return to task context**, then **Read this task response**. Desk reads
   that same turn's last supplied final answer, or its last readable assistant
   message when no final answer was supplied. The displayed phase and native
   turn status remain separate facts.
3. Choose **Return to task context** to inspect another supplied instruction, or
   **Previous task** / **Next task** to follow the original's supplied turn order.
4. Choose **Return to original passage** to restore the excerpt, text selection,
   Find position and reading view. The outer Return control still leads back to
   B's same unsent draft, saved follow-up or captured instruction.

A task with no supplied readable user instruction reports that availability;
its own response can still be read. An earlier instruction or a later answer
belongs to another task and is not used in its place. Navigating task context,
instruction and response uses the already-read original snapshot. **Refresh
original** is the separate action that reads the native source again.

## Jump to a remembered user instruction

Within task context, enter a phrase in **Jump to supplied user instruction** and
choose **Find instructions**. The search uses all addressable user-message items
in the already-loaded original, with literal punctuation and NFKC/casefold Unicode
matching. Assistant replies, tool output and the reader’s role labels are excluded.

Results show the exact thread/turn/item and an original-text snippet, up to **20
matching instructions per page**. Use **Next instruction matches** to reach later
rows. Choose **Read task for this instruction** to open that exact turn’s existing
task context; its matching instruction is emphasized. **Read full instruction**
highlights the original phrase in its complete text window, and **Read this task
response** reads that turn’s own reported response.

**Return to instruction matches** restores the entered query, result page, exact
row and reading position. **Return to original passage** restores the original
Find occurrence, selected excerpt and text window. **Refresh original** searches
the refreshed snapshot using the last submitted phrase while keeping any newer,
unsubmitted query text. Existing Plan drafts and prepared queues stay in place.

## Continue through ordinary preparation

- **Prepared work → Review draft and follow-ups** reads the same saved text independently of today's selected task. **Browse originals for this draft** explicitly chooses that row as the destination; review and append there using its normal save. The draft, saved queue and captured request each offer **Read referenced original**.
- **Save as follow-up** stores the current instruction, including the evidence
  block, in the existing queue. Edit/reorder/reuse controls retain ordinary queue
  revision and admission rules.
- **Run task** or **Send next** is the later, separate send action. The instruction
  includes the quote and its readable provenance as ordinary text.
- A retained Run request keeps the exact captured instruction even after its
  original draft is cleared or newer preparation is saved. **Review task request**
  reads that body; retry uses the original captured task rather than later edits.

Keep the embedded block and readable quote together. Editing or removing part of
the block makes it ordinary draft text; re-review A to create a fresh actionable
reference. Surrounding task text and a separate next-step note remain editable.

## Locate saved evidence later

Open **Prepared work**, keep the project and archive scope you need, and enter
at least two characters in **Find a phrase in saved preparation**. Choose **Search** or press
Enter. Literal, Unicode-normalized matches identify the original saved owner and
whether the words belong to its draft, saved follow-up, captured instruction or
unconfirmed Run request. **Next matches** and **Previous matches** page results.

Choose the result to review that exact saved control. Your current task and any
unsaved preparation stay in place. Expand its referenced originals, read the
retained excerpt in A, then return to the same editor or captured instruction.
The ordinary **Prepared follow-ups** and **Check Run request** controls also expose
these references directly beside their saved instruction.

## Runnable examples

The [deterministic lifecycle example](../examples/evidence_preparation.py) uses a
synthetic source with two identical Unicode quotes and a removed A folder. It
checks the actual local draft, Prepared snapshot, queue and captured-request
domain, cold reopen, exact source resolution, and saved-quote retention when the
source changes or disappears. Its supplied turn transport returns an unconfirmed
admission for local request review.

From a source checkout with Python 3.11+:

```sh
DESK_TEST_TEMP="$PWD/temp/evidence-example" PYTHONPATH=. python3 examples/evidence_preparation.py
```

The [installed browser example](../examples/check_native_evidence_preparation.py)
drives the actual reader and draft controls at 1250- and 390-pixel widths using
controlled local native history. It selects the second quote in a long command
output, reviews/appends locally, returns to its exact text window, and exercises
changed/missing-source and cold-return paths. Both examples use generated fixture
content. See [the complete workbench guide](workbench.md) for ordinary preparation
and admission controls.

The [browser-sample task-context check](../examples/check_browser_preview_task_context.py)
reproduces tool evidence → its own supplied instruction → that task's response →
the original passage → the unsent outer task across all three sample histories.
It also checks a targeted no-input task without substituting a neighboring prompt.
After building the maintained preview:

```sh
python3 examples/check_browser_preview_task_context.py --site temp/browser-preview/demo --evidence temp/browser-preview/task-context-checks
python3 examples/check_browser_preview_task_context.py --embedded --site temp/browser-preview/embedded --evidence temp/browser-preview/embedded-task-context-checks
```

The [installed instruction-jump check](../examples/check_native_instruction_jump.py)
uses 27 supplied matching instructions, literal Unicode/punctuation, late source
text, keyboard result paging and each task’s own historical response. At 1250/390
it preserves a genuinely pointer-selected original quote, the result row/query,
current Plan and both queues, and the outer unsent preparation editor.
