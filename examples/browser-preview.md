# No-install browser sample

[Open the interactive preview](https://blucca.github.io/codex-desk/demo/).

Choose **Find the sample answer** in the preview header to open content search with `retry budget` filled in, or use **Find a decision in past work** and enter it yourself. Then choose **Search** → **Index existing Codex history** → **Read original conversation** → **Back to search** → **Continue this conversation**. Write a Plan draft, save two follow-ups, reorder them, then choose **Prepared work**. Review and append a queued instruction to its own draft, **Save draft and open** to return to that exact unsent Plan, then reload to find the same preparation.

To carry an original excerpt into another task, open **Sample documentation review**, write an unsent Plan, and use **Browse existing Codex sessions** to **Read original conversation** for the checkout sample. Select the retry rule and choose **Review evidence for task** → **Append to draft**. Reload, then expand **Referenced originals in this draft** and choose **Read referenced original** to revisit the same checkout answer and return to the unsent documentation Plan. See the [evidence preparation guide](../docs/evidence-preparation.md).

## Find saved preparation

After saving a draft or follow-up, choose **Prepared work**, enter a remembered phrase in **Find a phrase in saved preparation**, then choose **Search**. **Project folder** scopes both the owner list and matches. Search treats punctuation literally and normalizes case and Unicode; it does not search unsaved edits or hide unrelated saved owners in the chosen scope.

Choose **Review saved draft** or **Review saved follow-up** to revisit its exact owner. For a draft containing a referenced original, **Read referenced original** opens the retained quote and returns to the same local editor. To try the ordinary queue path, save that referenced draft with **Save as follow-up**, choose **Edit** in **Prepared follow-ups**, make an unsaved change, and choose **Read referenced original**. **Return to saved follow-up** restores that unsent instruction, selection and scroll position without saving or sending it.

The preview uses three primary synthetic histories and an independent linked original, the maintained Desk interface and a sample-only API implemented in the browser. Preparation is saved in namespaced browser storage. **Reset sample** clears only these sample keys. The installed workbench uses native Codex history and its local SQLite database; follow the [installer](../README.md#install-the-preview) for your own work.

## Rebuild and check

From the repository root, with Python 3.11+:

```sh
python3 examples/build_browser_preview.py --out temp/browser-preview/demo
```

Serve the output with any static HTTP server. For reproducible desktop and mobile browser acceptance, use a Playwright Python environment:

```sh
python3 examples/check_browser_preview.py --site temp/browser-preview/demo --evidence temp/browser-preview/checks
```

Use `--chromium /path/to/chromium` to reuse an installed browser. The checker exercises explicit indexing, exact original IDs, continuation, saved Plan/ordered follow-ups, exact task-response reading, reviewed original A into unsent B, cold source return, local review and explicit Save-and-open, reload and scoped reset. It also checks literal Prepared lookup across all three primary sample projects, duplicate saved owners without replacing unsaved editors, exact project scope, retained originals and ordinary queued-instruction return. The embedded build is checked in an actual iframe. Application requests cannot escape to the static HTTP server.

`browser-preview/preview-api.js` contains only sample behavior. `build_browser_preview.py` copies maintained assets and applies the preview label, route-relative assets, install actions and a preview-specific selection key. Production runtime files are unchanged.

## Check session reading returns

The opt-in acceptance fixture keeps the four original sample identities and adds
long parent command/MCP results, reported native steps/changes and an unsent
sample input request. The default build has three short primary histories and the independent long linked original.

```sh
python3 examples/build_browser_preview.py --session-reading-fixture --out temp/browser-preview/reading
python3 examples/build_browser_preview.py --session-reading-fixture --embedded --out temp/browser-preview/reading-embedded
python3 examples/check_browser_preview_links.py --session-reading --site temp/browser-preview/reading --embedded-site temp/browser-preview/reading-embedded --evidence temp/browser-preview/reading-checks
```

This checks ordinary and actual-iframe hosting at 1250/390: A→B→A restores the
exact source, disclosures, pre-scroll and viewport while keeping Plan drafts,
ordered queues and B's unsent answers; new sample output waits for explicit
**Latest output**. A real reload reads fresh source text and restores only bounded
reading metadata. Delayed namespace/selection and explicit source/Latest intents
keep their own task; a moved item ID cannot substitute for the captured turn.
**Reset sample** clears sample reading metadata and preparation, retaining the
installed workbench's keys. Reading metadata uses a preview-specific storage key.

To rerun only reading transitions, use
`check_browser_preview_session_reading.py --site OUTPUT --evidence EVIDENCE`,
adding `--embedded` for the iframe build. The JSON receipts and screenshots retain
each exact-source comparison; the fixture traps every native task/response path.

The same opt-in fixture also exercises **Read first new activity**:

```sh
python3 examples/check_browser_preview_new_activity.py --site temp/browser-preview/reading --evidence temp/browser-preview/new-activity
python3 examples/check_browser_preview_new_activity.py --site temp/browser-preview/reading-embedded --embedded --evidence temp/browser-preview/new-activity-embedded
```

At 1250/390, the checker updates an earlier native command, opens that exact item
without marking it reviewed, returns between saved tasks and reloads fresh source.
Held event responses and deliberate Latest frames keep review on the captured
displayed frontier while later material remains new. A moved source cannot be
recovered from cached event replay. Sample review metadata has its own storage key;
**Reset sample** clears it along with sample reading places and preparation.

For iframe hosting, add `--embedded` when building. Installer links then open separately while the sample preparation stays in the original frame. Check both hosting modes with:

```sh
python3 examples/build_browser_preview.py --embedded --out temp/browser-preview/embedded
python3 examples/check_browser_preview.py --site temp/browser-preview/embedded --evidence temp/browser-preview/embedded-checks
python3 examples/check_browser_preview_links.py --site temp/browser-preview/demo --embedded-site temp/browser-preview/embedded --evidence temp/browser-preview/link-checks
```

To rerun only Prepared lookup and original-source return:

```sh
python3 examples/check_browser_preview_lookup.py --site temp/browser-preview/demo --evidence temp/browser-preview/lookup-checks
python3 examples/check_browser_preview_lookup.py --embedded --site temp/browser-preview/embedded --evidence temp/browser-preview/embedded-lookup-checks
```

## Read the task behind sample evidence

In an original sample conversation, use **Read containing task** beside a command
item. Read its full supplied instruction, then **Read this task response**.
**Return to task context** restores the reviewed control and scroll;
**Return to original passage** restores the original Find/selection/window.
The maintained checker exercises these paths at both widths, ordinary and in an
actual iframe, alongside the existing Prepared lookup workflow.

```sh
python3 examples/check_browser_preview_task_context.py --site temp/browser-preview/demo --evidence temp/browser-preview/task-context
```

## Changed saved work and review return

The default sample can group its three saved conversations without inventing a
review baseline. The existing reading fixture also supplies parent-task events
for **Changed saved work** → the saved original passage → **Read first new
activity** → **Mark displayed updates reviewed** → **Back to Changed work**.
The checker preserves the overview row and project/title/archive/page scope,
including when a reviewed row no longer belongs in Changed. Background native
material updates only the small dot while another task's draft, paused queues,
unsent answer and editor caret remain unchanged.

```sh
python3 examples/check_browser_preview_changed_work.py --ordinary --site temp/browser-preview/demo --evidence temp/browser-preview/changed-normal
python3 examples/check_browser_preview_changed_work.py --site temp/browser-preview/reading --evidence temp/browser-preview/changed-reading
python3 examples/check_browser_preview_changed_work.py --embedded --site temp/browser-preview/reading-embedded --evidence temp/browser-preview/changed-embedded
```

Each command checks 1250/390 against the generated maintained assets. Receipts
record compact native-home-bound metadata, exact source IDs, GET-only overview
and review reads, and zero native task or response admissions. Reset checks wait
for the sample document's actual reload, including inside the iframe.

## Read the reported linked original and reuse its exact quote

The checkout parent explicitly reports `sample-child-thread` in its collaboration
item. That fourth history is the independent original, with a completed response
and a missing project folder. Recent indexing counts all four histories and their
actual supplied items; the three saved primary tasks stay separate from the child.

1. Resume **Sample checkout retry decision**, retain an unsent **Plan** and two
   queued instructions. This existing parent draft is the B destination below.
2. Open **Changed saved work**. On the default build, use **All saved work** after
   inspecting the empty Changed scope. The opt-in reading build supplies real
   parent events: the checker updates the parent collaboration result, opens its Changed row
   and chooses **Read first new activity**, keeping the review frontier unchanged.
3. Expand parent collaboration and choose **Read linked agent original ·
   sample-child-thread**. The maintained controller performs one native-home-bound
   `GET /api/native/evidence-source?home=…&thread=sample-child-thread`.
4. Find `Child decisive evidence — café🙂 项目 exact source.`, then press **F3**
   for the second occurrence. **Copy full item text** includes all 1,200 source
   lines. Select that second exact quote and choose **Review evidence for task**.
5. Review the captured child IDs/quote and the existing parent/B **Plan**, then
   **Append to current draft** once. Both ordered queues and the other saved owner
   remain unchanged. **Return to parent activity** restores the exact parent passage.
6. Open the actual saved draft reference. Its second child quote is highlighted;
   return restores B's editor caret/direction/scroll and the parent passage.
   **Back to Changed work** restores the same row and project/title/archive/page scope.

Run the connected workflow at 1250/390, direct and in an actual iframe:

```sh
python3 examples/check_browser_preview_linked_original.py --ordinary --site temp/browser-preview/demo --evidence temp/browser-preview/linked-normal
python3 examples/check_browser_preview_linked_original.py --ordinary --embedded --site temp/browser-preview/embedded --evidence temp/browser-preview/linked-normal-iframe
python3 examples/check_browser_preview_linked_original.py --site temp/browser-preview/reading --evidence temp/browser-preview/linked-reading
python3 examples/check_browser_preview_linked_original.py --embedded --site temp/browser-preview/reading-embedded --evidence temp/browser-preview/linked-reading-iframe
```

The source reads create no child saved task, draft, queue, native event feed or
native admission. Ordinary Recent, Find and source-return controls use the same
reported child original and exact source API.

## Follow newly supplied original items

All four builds start with the same four histories: 13 supplied items in the
ordinary builds, or 15 with the opt-in reading fixture. **Add sample original
items** adds exactly five source-only native items to `sample-child-thread` on the
current sample page, across two new turns. The first is a user instruction;
the final answer of the later turn remains distinct. The button leaves saved
tasks, drafts, queues, Activity and its review frontier unchanged and does not
read an original or send a native task.

1. Keep **Sample documentation review** selected with an unsent **Plan** and two
   queued instructions. In **Browse existing Codex sessions**, choose **Native
   history** → **Archived conversations**, search `linked retry original`, then
   **Read original conversation**. Or use **Read original by ID** with
   `sample-child-thread`.
2. Find `Child decisive evidence — café🙂 项目 exact source.`. Select the first
   occurrence, choose **Review evidence for task** → **Append to draft** once,
   then use **Next match** to read the second occurrence in the long native item.
   Close the reader and its conversation catalog. That successful fresh read
   establishes the supplied-item snapshot.
3. Choose **Add sample original items**, then change between 1250px and 390px.
   Deliberately read the same original again by title or ID. The prior text
   window, disclosures and actual first visible literal character return in fresh
   source text, even though scroll distances change. The former visit's Find and
   selected text end when that reader closes.
4. The reader reports **New since previous fresh original read · 5 newly supplied
   native items.** Choose **Read first newly supplied item**. It opens
   `sample-child-supplied-turn` / `sample-child-supplied-question`, whose text begins
   `FIRST NEW SAMPLE ORIGINAL ITEM`, rather than `LATER SAMPLE FINAL ANSWER`.
5. **Return to original passage** restores the view, Find and selection from
   immediately before the jump. Open the saved first quote from B's actual draft
   reference: that explicit first occurrence wins over the remembered later
   passage. Return keeps B's editor caret/direction/scroll, Plan and both queues.
   Reload keeps preparation and reading/snapshot metadata, leaving the original
   closed with no automatic original read or task run.

“New” compares ordered native turn/item identities against the previous
successful fresh original read in this browser/native home. It does not track
consumed/unread items, and an existing item's text edit is not a new identity.
Successful fresh reads advance that snapshot. **Read first new activity** and
**Mark displayed updates reviewed** instead use the saved task's recorded updates
and review frontier, which may include changes to earlier items. Reading new
original items does not mark activity reviewed. Exact saved-reference/item/response
targets keep their own passage and leave the ordinary snapshot intact.

With the four outputs built above, run the maintained checker in each mode:

```sh
python3 examples/check_browser_preview_following_original.py --site temp/browser-preview/demo --evidence temp/browser-preview/following-normal
python3 examples/check_browser_preview_following_original.py --embedded --site temp/browser-preview/embedded --evidence temp/browser-preview/following-iframe
python3 examples/check_browser_preview_following_original.py --rich --site temp/browser-preview/reading --evidence temp/browser-preview/following-rich
python3 examples/check_browser_preview_following_original.py --rich --embedded --site temp/browser-preview/reading-embedded --evidence temp/browser-preview/following-rich-iframe
```

Each command checks both 1250→390 and 390→1250, using a real iframe for
`--embedded`. Receipts measure the exact native UTF-16 character position with
text-node Ranges, not an inferred line or pixel count. They also check the first
supplied instruction, backwards pointer selection and Find return, the saved
first quote, B's actual editor and both queues, zero automatic original reads or
native admissions, and metadata-only storage. **Reset sample** clears its own
original snapshot/reading/preparation keys, including a late pagehide write, while
retaining installed-workbench and unrelated same-origin keys.

## Keep the command output passage when its status header changes

**Prepare sample command output** replaces only the existing child command's
synthetic source content with long output and `inProgress` / no exit code. Four
histories and the initial 13 ordinary / 15 rich item counts stay unchanged. This
preparation and **Complete sample command** change neither saved-task Activity
nor its review frontier, B's draft/queues or native task admission.

Keep B's unsent Plan and two queues selected. Prepare the command, read
`sample-child-thread` by ID, then Find `HEADER OUTPUT PASSAGE — café🙂 项目.` in
the middle output window. Close the original and its catalog, choose **Complete
sample command**, resize to the opposite narrow/wide width, and deliberately
reopen. The output is byte-for-byte identical; only the generated status/exit
header changed. The actual first visible native-output character returns, rather
than an old absolute offset into the shorter header-plus-output projection.

The same status button is available inside the original reader. It toggles back
with **Restore sample command in progress**. Use **Refresh original** to read
that header change. The maintained checker holds this fresh read, changes status
and resizes in the opposite direction before releasing it, then verifies the
output-relative UTF-16 character, Find and a real backwards pointer selection.
It also checks **Read containing task** → held Refresh → **Return to original
passage**. Returning to B preserves its exact editor selection, scroll, Plan and
both queues; reload retains metadata without automatically reading an original.
Saved quotations remain explicit native source targets. A deliberate new Find,
page or scroll during a held read stays the newer reading intent; changing only
the layout width does not replace the prior output passage.

Run all four existing builds, with both resize directions in every command:

```sh
python3 examples/check_browser_preview_command_header.py --site temp/browser-preview/demo --evidence temp/browser-preview/command-header-normal
python3 examples/check_browser_preview_command_header.py --embedded --site temp/browser-preview/embedded --evidence temp/browser-preview/command-header-iframe
python3 examples/check_browser_preview_command_header.py --rich --site temp/browser-preview/reading --evidence temp/browser-preview/command-header-rich
python3 examples/check_browser_preview_command_header.py --rich --embedded --site temp/browser-preview/reading-embedded --evidence temp/browser-preview/command-header-rich-iframe
```

Receipts use text-node Ranges to measure the literal first visible output glyph,
not line estimates or equal scroll pixels. Only numeric command-output-boundary
metadata is added to reading checkpoints; native output bodies, Find text and
selections remain outside those records.

## Choose an exact occurrence from original Find matches

Keep **Sample documentation review** selected with its unsent Plan and two queued
instructions. Read `sample-child-thread` by ID, then Find
`Child decisive evidence — café🙂 项目 exact source.`. This existing original has
two identical quotes in one long native item; this workflow adds no sample data,
new source items, Activity events or task admission.

Choose **Show Find matches**. Focus **Read match 2** and press Enter to open the
second occurrence directly, including its exact native turn/item/span. Select
the quotation backwards with the pointer. **Read containing task** → **Return
to original passage** restores that second occurrence, Find and real selection.
**Return to Find matches** returns to the same submitted query, occurrence page
and row. Click **Read match 1**, then immediately press F3: it continues to the
second occurrence from the ordinal you just selected. Return to B's actual
editor keeps its caret/direction/scroll, Plan and both queues.

The overview uses the existing submitted Find groups, at most 20 occurrences per
page, within this already loaded original. It performs no additional source read,
index pass or other-history search. Exact duplicate spans remain distinct.

```sh
python3 examples/check_browser_preview_find_matches.py --site temp/browser-preview/demo --evidence temp/browser-preview/find-matches-normal
python3 examples/check_browser_preview_find_matches.py --embedded --site temp/browser-preview/embedded --evidence temp/browser-preview/find-matches-iframe
python3 examples/check_browser_preview_find_matches.py --rich --site temp/browser-preview/reading --evidence temp/browser-preview/find-matches-rich
python3 examples/check_browser_preview_find_matches.py --rich --embedded --site temp/browser-preview/reading-embedded --evidence temp/browser-preview/find-matches-rich-iframe
```

Each command checks 1250px and 390px, with an actual iframe in `--embedded` mode.
Receipts bind each row's global occurrence ordinal to the supplied native source,
retain Enter and pointer choices, and check immediate F3 continuation, exact
containing-task passage return and unchanged B/source/review state.
