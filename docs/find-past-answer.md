# Find a past Codex answer and reopen its task

Remember a phrase from a decision or test result, but not the conversation title? Codex Desk can search visible text from your local Codex history and return you to the original saved thread.

## Install once, then find the answer

Use the [one-command installer](../README.md#install-the-preview) with your existing Codex CLI and sign-in. Desk opens the printed local browser URL. For another history location, append `--codex-home /your/codex-home` to the launch command.

1. **Open content search.** On the first screen choose **Find a decision in past work**. In an open workbench, use **Search saved content** in the sidebar.
2. **Index unopened history.** Choose **Index existing Codex history**. This explicitly reads up to 200 recently updated native conversations into Desk's local cache. Watch the seen/indexed/unchanged/failed counts, then open **Index coverage and text limits** to see the retained coverage. Indexing does not create Desk conversation bindings or send a task.
3. **Search a remembered phrase.** Keep **All indexed projects** for the first search. Enter 2–200 characters actually present in your past answer or tool output—for example, `retry budget`—and choose **Search** or press Enter. Search is literal, case-insensitive and Unicode-normalized. Choose an available **Project folder (optional)** to narrow subsequent searches to an exact folder. Choose **Search** again after indexing to refresh the matches.
4. **Open the original evidence.** Check the result's conversation, project folder and snippet. Choose **Open matching native activity** for indexed native history, or **Open matching activity** for Desk-cached work. Desk opens the original saved native thread, expands its matching evidence and focuses the matched message or tool result. A native-history match uses **Current Codex settings**; a Desk-cached match keeps its saved profile. Opening a match submits no task.
5. **Prepare what comes next.** Read the result in context, then write your next instruction and wait for **Draft saved locally**, or choose **Save as follow-up**. Use **Run task** or **Send next** when ready. Reopening Desk with the same state directory restores the saved preparation.

## What the index covers

- Each pass starts with the current native conversation list and stops at 200 recently updated conversations. **Index existing history again** refreshes that recent window and skips unchanged snapshots; it does not advance automatically into older history.
- Native snapshots retain the newest readable items first: up to **5,000 items** and **2,000,000 characters per conversation**, with **200,000 characters per item**. Coverage reports shortened, omitted, unsupported and unreadable items from the supplied native reads.
- Results include readable messages, command output, file changes and tool evidence, plus saved Desk drafts and follow-ups. The dialog shows up to **30 matching items**; narrow the phrase or project when more matches exist. **Include archived sessions** includes locally archived Desk entries; opening one restores its entry.
- Indexed text stays in the local Desk SQLite database across restarts. **Cancel indexing** keeps already cached items; **Retry** starts another pass. Closing the search dialog leaves an active scan running.

For work beyond the recent window, use **Browse all conversations** on the first screen or **Browse existing Codex sessions** in the sidebar. Search its title, use **Load more** as needed, and resume it; opening it caches readable evidence for content search. The saved project folder must still exist to reopen the conversation. If the original evidence has changed, Desk keeps the cached hit visible rather than navigating to a different item.

[中文首次使用指南](first-project.zh-CN.md) · [Full workflow reference](workbench.md) · [Ask for task help](https://github.com/blucca/codex-desk/issues/new?template=task-help.yml)
