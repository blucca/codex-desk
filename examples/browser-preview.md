# No-install browser sample

[Open the interactive preview](https://blucca.github.io/codex-desk/demo/).

Choose **Find the sample answer** in the preview header to open content search with `retry budget` filled in, or use **Find a decision in past work** and enter it yourself. Then choose **Search** → **Index existing Codex history** → **Read original conversation** → **Back to search** → **Continue this conversation**. Write a Plan draft, save two follow-ups, reorder them, then choose **Prepared work**. Review and append a queued instruction to its own draft, **Save draft and open** to return to that exact unsent Plan, then reload to find the same preparation.

To carry an original excerpt into another task, open **Sample documentation review**, write an unsent Plan, and use **Browse existing Codex sessions** to **Read original conversation** for the checkout sample. Select the retry rule and choose **Review evidence for task** → **Append to draft**. Reload, then expand **Referenced originals in this draft** and choose **Read referenced original** to revisit the same checkout answer and return to the unsent documentation Plan. See the [evidence preparation guide](../docs/evidence-preparation.md).

## Find saved preparation

After saving a draft or follow-up, choose **Prepared work**, enter a remembered phrase in **Find a phrase in saved preparation**, then choose **Search**. **Project folder** scopes both the owner list and matches. Search treats punctuation literally and normalizes case and Unicode; it does not search unsaved edits or hide unrelated saved owners in the chosen scope.

Choose **Review saved draft** or **Review saved follow-up** to revisit its exact owner. For a draft containing a referenced original, **Read referenced original** opens the retained quote and returns to the same local editor. To try the ordinary queue path, save that referenced draft with **Save as follow-up**, choose **Edit** in **Prepared follow-ups**, make an unsaved change, and choose **Read referenced original**. **Return to saved follow-up** restores that unsent instruction, selection and scroll position without saving or sending it.

The preview uses three synthetic conversations, the maintained Desk interface and a sample-only API implemented in the browser. Preparation is saved in namespaced browser storage. **Reset sample** clears only these sample keys. The installed workbench uses native Codex history and its local SQLite database; follow the [installer](../README.md#install-the-preview) for your own work.

## Rebuild and check

From the repository root, with Python 3.11+:

```sh
python3 examples/build_browser_preview.py --out temp/browser-preview/demo
```

Serve the output with any static HTTP server. For reproducible desktop and mobile browser acceptance, use a Playwright Python environment:

```sh
python3 examples/check_browser_preview.py --site temp/browser-preview/demo --evidence temp/browser-preview/checks
```

Use `--chromium /path/to/chromium` to reuse an installed browser. The checker exercises explicit indexing, exact original IDs, continuation, saved Plan/ordered follow-ups, exact task-response reading, reviewed original A into unsent B, cold source return, local review and explicit Save-and-open, reload and scoped reset. It also checks literal Prepared lookup across all three sample projects, duplicate saved owners without replacing unsaved editors, exact project scope, retained originals and ordinary queued-instruction return. The embedded build is checked in an actual iframe. Application requests cannot escape to the static HTTP server.

`browser-preview/preview-api.js` contains only sample behavior. `build_browser_preview.py` copies maintained assets and applies the preview label, route-relative assets, install actions and a preview-specific selection key. Production runtime files are unchanged.

## Check session reading returns

The opt-in acceptance fixture keeps the three original sample identities and adds
long command/MCP results, collaboration, reported native steps/changes and an unsent
sample input request. The normal public build keeps its existing short histories.

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
