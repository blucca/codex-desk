# No-install browser sample

[Open the interactive preview](https://blucca.github.io/codex-desk/demo/).

Choose **Find the sample answer** in the preview header to open content search with `retry budget` filled in, or use **Find a decision in past work** and enter it yourself. Then choose **Search** → **Index existing Codex history** → **Read original conversation** → **Back to search** → **Continue this conversation**. Write a Plan draft, save two follow-ups, reorder them, then reload to find the same preparation.

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

Use `--chromium /path/to/chromium` to reuse an installed browser. The checker exercises explicit indexing, exact original IDs, continuation, saved Plan/ordered follow-ups, reload and scoped reset; it rejects application requests that escape to the static HTTP server.

`browser-preview/preview-api.js` contains only sample behavior. `build_browser_preview.py` copies maintained assets and applies the preview label, route-relative assets, install actions and a preview-specific selection key. Production runtime files are unchanged.
