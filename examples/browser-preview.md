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
