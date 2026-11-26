# Find a past Codex answer, read it, then continue

Remember a phrase from a decision or test result, but not the conversation title? Search your local Codex history and read the original answer first. Continuing the task is a separate choice.

[Watch the 20-second local demo](find-answer.gif) — synthetic checkout history.

## Install once, then find the answer

Use the [one-command installer](../README.md#install-the-preview) with your existing Codex CLI and sign-in. Desk opens the printed local browser URL. For another history location, append `--codex-home /your/codex-home` to the launch command.

1. **Open content search.** On the first screen choose **Find a decision in past work**. In an open workbench, use **Search saved content** in the sidebar.
2. **Index unopened history.** Choose **Index existing Codex history**. This explicitly reads up to 200 recently updated native conversations into Desk's local cache. Watch the seen/indexed/unchanged/failed counts, then open **Index coverage and text limits** to see the retained coverage. Indexing does not create Desk conversation bindings or send a task.
3. **Search a remembered phrase.** Keep **All indexed projects** for the first search. Enter 2–200 characters actually present in your past answer or tool output—for example, `retry budget`—and choose **Search** or press Enter. Search is literal, case-insensitive and Unicode-normalized. Choose an available **Project folder (optional)** to narrow subsequent searches to an exact folder. Choose **Search** again after indexing to refresh the matches.
4. **Read the original evidence.** Check the result's conversation, project folder and snippet, then choose **Read original conversation** on an indexed native result or a cached activity result with its original thread. The read-only reader opens its exact original turn/item and highlights the saved phrase. It works even after the project folder has been removed, without importing or resuming the thread. Your selected task and draft stay unchanged. **Back to search** or **Close** returns to the same query and results.
5. **Continue only when ready.** Choose **Continue this conversation** to resume the original native thread with **Current Codex settings**. The saved project folder must exist for this step. Write your next instruction and wait for **Draft saved locally**, or choose **Save as follow-up**. Use **Run task** or **Send next** when ready; relaunching with the same state directory restores the preparation. For Desk-cached work, **Open matching activity** uses its saved binding and profile.

## Reading a long conversation

The reader shows **40 original items per page**. **Previous items** and **Next items** replace the page; it initially selects the page containing the matching native turn and item. Messages and tool evidence are displayed as readable text, with command results expanded at the match.

Each item shows a window of up to **20,000 text characters**. For longer output, **Earlier text** and **Later text** reveal other windows; the character range and total stay visible. The reader reports unsupported or unreadable items. If the saved turn/item or phrase is missing from the fresh native read, it reports that accurately while keeping the rest of the conversation readable. **Retry read** retries a failed native read.

## What the index covers

- Each pass starts with the current native conversation list and stops at 200 recently updated conversations. **Index existing history again** refreshes that recent window and skips unchanged snapshots; it does not advance automatically into older history.
- Native snapshots retain the newest readable items first: up to **5,000 items** and **2,000,000 characters per conversation**, with **200,000 characters per item**. Coverage reports shortened, omitted, unsupported and unreadable items from the supplied native reads.
- Results include readable messages, command output, file changes and tool evidence, plus saved Desk drafts and follow-ups. The dialog shows up to **30 matching items**; narrow the phrase or project when more matches exist. **Include archived sessions** includes locally archived Desk entries; opening one restores its entry.
- Indexed text stays in the local Desk SQLite database across restarts. **Cancel indexing** keeps already cached items; **Retry** retries a cancelled or failed pass. Closing the search dialog leaves an active scan running.

For work beyond the recent index window, use **Browse all conversations** on the first screen or **Browse existing Codex sessions** in the sidebar. Search its title, use **Load more** as needed, and resume it when the project folder exists; opening it caches readable evidence for content search.

[中文首次使用指南](first-project.zh-CN.md) · [Full workflow reference](workbench.md) · [Ask for task help](https://github.com/blucca/codex-desk/issues/new?template=task-help.yml)
