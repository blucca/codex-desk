# Find a past Codex answer, read it, then continue

Remember a phrase from a decision or test result, but not the conversation title? Search your local Codex history and read the original answer first. Continuing the task is a separate choice.

[Try the interactive browser sample](https://blucca.github.io/codex-desk/demo/) — find the checkout retry decision, read its original answer, save a next task, then reload to return. No install is needed for this sample.

[Watch the 20-second local demo](find-answer.gif) — synthetic checkout history.

## Install once, then find the answer

Use the [one-command installer](../README.md#install-the-preview) with your existing Codex CLI and sign-in. A working Desktop bundled reader is another option: follow the [macOS](find-desktop-answer.macos.md) or [Windows](find-desktop-answer.windows.md) guide and pass it with `--codex`, without installing a separate CLI. Desk opens the printed local browser URL. For another history location, append `--codex-home /your/codex-home` to the launch command.

The live catalog and original reader use `--codex-home`, otherwise `CODEX_HOME`, otherwise this launch environment's `~/.codex`. Content search uses the retained `--state-dir` database: changing the native home alone keeps previously indexed hits. When switching to a separate set of native histories, use a different `--state-dir` and retain the old database and launch options for its saved preparation. To read old cached originals, relaunch with their original home and state directory.

1. **Open content search.** On the first screen choose **Find a decision in past work**. In an open workbench, use **Search saved content** in the sidebar.
2. **Index unopened history.** Choose **Index existing Codex history**. This explicitly reads up to 200 recently updated native conversations into Desk's local cache. Watch the seen/indexed/unchanged/failed counts, then open **Index coverage and text limits** to see the retained coverage. Indexing does not create Desk conversation bindings or send a task.
3. **Search a remembered phrase.** Keep **All indexed projects** for the first search. Enter 2–200 characters actually present in your past answer or tool output—for example, `retry budget`—and choose **Search** or press Enter. You can submit the query while indexing; the explicit scan's completion refreshes an unchanged submitted query once while the search dialog stays active. Search is literal, case-insensitive and Unicode-normalized. Choose an available **Project folder (optional)** to narrow subsequent searches to an exact folder. After editing the phrase or scope, choose **Search** to submit those changes.
4. **Read the original evidence.** Check the result's conversation, project folder and snippet, then choose **Read original conversation** on an indexed native result or a cached activity result with its original thread. The read-only reader opens its exact original turn/item and highlights the saved phrase. It works even after the project folder has been removed, without importing or resuming the thread. Your selected task and draft stay unchanged. **Next matches** / **Previous matches** reaches later result pages. **Back to search** or **Close** returns to the same query, page and results.
5. **Continue only when ready.** Choose **Continue this conversation** to resume the original native thread with **Current Codex settings**. The saved project folder must exist for this step. Write your next instruction and wait for **Draft saved locally**, or choose **Save as follow-up**. Use **Run task** or **Send next** when ready; relaunching with the same state directory restores the preparation. For Desk-cached work, **Open matching activity** uses its saved binding and profile.

## Reading a long conversation

The reader shows **40 original items per page**. **Previous items** and **Next items** replace the page; it initially selects the page containing the matching native turn and item. Messages and tool evidence are displayed as readable text, with command results expanded at the match.

Each item shows a window of up to **20,000 text characters**. For longer output, **Earlier text** and **Later text** reveal other windows; the character range and total stay visible. The reader reports unsupported or unreadable items. Turns that produced no items still show their native ID, status and reported error message; they are counted separately from original items. If the saved turn/item or phrase is missing from the fresh native read, it reports that accurately while keeping the rest of the conversation readable. **Retry read** retries a failed native read.

**Find in this original conversation** searches the complete readable text supplied by that native read, including other pages and text beyond the cached index prefix. Enter a literal phrase and choose **Find**; **Next match** / **Previous match** (F3 / Shift+F3 while the reader is open) visits occurrences and highlights the original characters. No new native read or task is started by finding text.

**Copy full item text** copies the whole readable message/tool item, not just its visible 20,000-character window. **Copy source reference** copies the conversation, native thread/turn/item IDs and project folder for your current investigation. These actions leave your saved preparation unchanged.

**Previous items** and **Next items** move keyboard focus into the newly displayed page, including a final page without a saved-text match. Tab then reaches that page's item controls; F3 remains local to the original reader.

## What the index covers

- The initial pass reads up to 200 recent conversations. **Refresh recent history** starts at the current top and skips unchanged snapshots. **Index next older conversations** explicitly reads the next bounded group using retained native page progress; it never starts automatically. Cancellation and restart keep unread page rows for **Continue indexing**. **Retry unread histories** retries retained failed reads. An active older boundary is not rewound by recent refresh, and older cached evidence remains.
- Native snapshots retain the newest readable items first: up to **5,000 items** and **2,000,000 characters per conversation**, with **200,000 characters per item**. Coverage reports shortened, omitted, unsupported and unreadable items from the supplied native reads.
- Results include readable messages, command output, file changes and tool evidence, plus saved Desk drafts and follow-ups. The dialog shows **30 matching items per page**; use **Next matches** / **Previous matches** to reach the rest, or narrow the phrase/project. **Include archived sessions** includes locally archived Desk entries; opening one restores its entry.
- Indexed text stays in the local Desk SQLite database across restarts. **Cancel indexing** keeps already cached items; **Continue indexing** resumes a cancelled or interrupted pass. Closing the search dialog leaves an active scan running. Progress belongs to the launch Codex home; a different home starts its own recent pass.
- Completion preserves unsent edits, reader/result focus and navigation. If you closed the dialog or are inspecting an existing result, choose **Search** when you return to update the matches. A pending submitted search settles before its one fresh lookup; a newer submitted query takes precedence.

For work beyond the recent index window, choose **Index next older conversations** to extend content search explicitly, or use **Browse all conversations** on the first screen or **Browse existing Codex sessions** in the sidebar. Search its title and use **Load more** as needed. Choose **Read original conversation** on any catalog row to read that history without importing or resuming it, even when its folder is gone. **Back to search** keeps your title query and loaded rows. Resume it when the folder exists if you want to continue; opening the workbench caches readable evidence for content search.

[Python snapshot-search example: original thread/turn/item IDs](native-history-search-example.md)

[中文首次使用指南](first-project.zh-CN.md) · [Full workflow reference](workbench.md) · [Ask for task help](https://github.com/blucca/codex-desk/issues/new?template=task-help.yml)

### Copy an ID for a later original read

In a loaded original’s reader header, **Copy native conversation ID** copies its
complete bare ID. Paste that value into **Native conversation ID** when browsing
originals. The copied ID belongs to the original you are reading—including a
linked child—not the task selected behind it. The action becomes available after
the native source is successfully read. **Copy source reference** beside each item
still copies the existing multiline provenance with conversation, turn and item.
