# Codex Desk workflow reference

[Install and first use](../README.md#install-the-preview) · [中文指南](first-project.zh-CN.md)

## Find a saved conversation by title

In **Open a project**, enter part of a conversation title in **Search conversation titles**, then click **Find existing sessions** or press Enter. For conversations from other projects, open **Browse existing Codex sessions** in the sidebar, enter the title text and click **Search titles**.

Project results match the conversation's exact saved working directory (`cwd`): a session started in a subfolder requires that folder or the global browser. The exact saved folder can be entered even after it has been removed: **Find existing sessions** still searches its titles, and **Read original conversation** opens the original evidence. Missing-folder results have no Resume action; starting a new conversation stays unavailable until the folder is restored. **Back to project results** retains the query, loaded pages and source row. Global browsing uses the selected Codex home. Search matches native extracted titles, not message text, command output or MCP results.

Editing the query clears old results and pagination; submit it again to search. Leave the title field blank to list conversations in that scope. **Load more** continues the same submitted title query and scope.

## Find a decision or test result in saved work

Choose **Find a decision in past work** on the first screen or **Search saved content** in the sidebar. For unopened native work, choose **Index existing Codex history**: an explicit local read of up to 200 recently updated conversations. Enter a phrase from an earlier task, reply or tool result, then **Search**. Select an available project for an exact folder scope, or keep **All indexed projects**. **Include archived sessions** makes locally archived Desk work available too.

Results show the project, conversation and a matching snippet. On a native result, **Read original conversation** reads the exact original turn/item in a separate read-only viewer, including when its working folder has been removed. It does not import or resume the thread, and preserves the selected task and draft. **Back to search** retains the query and results. **Continue this conversation** separately resumes the original thread with **Current Codex settings**, requiring the saved project folder to exist.

For Desk-cached work, **Open matching activity** returns to its saved binding and profile and reveals the matched evidence. A saved draft or prepared follow-up result reveals the existing instruction; it does not send it. Opening an archived Desk result restores its entry.

Content recall reads your private local Desk database: explicitly indexed native history, readable evidence cached when you open a native conversation, subsequent Desk activity, saved drafts and prepared follow-ups. Indexing and the original-conversation reader use native list/read requests without starting tasks. Native title browsing remains separate; opening an older conversation caches its readable evidence too. Search itself makes no native request or model turn, and cached evidence stays searchable after a Desk restart.

Queries are literal, Unicode-normalized and case-insensitive. The dialog shows up to 30 matching items. **Index coverage and text limits** reports cached native coverage; each conversation retains the newest readable items first, bounded at 5,000 items, 2,000,000 characters total and 200,000 characters per item. **Refresh recent history** refreshes the recent 200-conversation window and skips unchanged snapshots. **Index next older conversations** continues explicitly from retained native page progress. **Continue indexing** resumes unread rows after cancellation or restart; older cached evidence is retained. [Short answer-finding guide](find-past-answer.md).

The reader uses 40-entry pages (native items or turn-only outcomes) and 20,000-character text windows. Use **Previous items**／**Next items**, or **Previous entries**／**Next entries** when turn-only outcomes are present, and **Earlier text**／**Later text**. A turn with no items still shows its native ID, status and reported error message. Missing native IDs or changed phrases are reported while the original conversation remains readable; **Retry read** retries a failed read.

In the original reader, **Find in this original conversation** searches all readable supplied items, not only the current page/window. **Find** submits the literal phrase; **Previous match** / **Next match**, or reader-local Shift+F3 / F3, jumps to the exact item/window. **Copy full item text** copies the entire readable item; **Copy source reference** copies its conversation/thread/turn/item/project identity. None of these actions opens a task or changes preparation. Content-search results have **Previous matches** / **Next matches** pages; returning from the reader retains the submitted query and page.

## Prepare a task and come back later

Write your next task and select Work or Plan. **Draft saved locally** confirms the text and mode are saved for this specific Desk session. Reopen the page or restart Desk with the same state directory to recover them; restoration does not send a task. A failed task submission keeps its preparation. After restarting the server, open its newly printed complete launch URL to restore browser access.

If another tab changes the same draft, choose **Keep this tab draft** or **Load saved draft** before saving or sending again. Sending clears only the preparation actually accepted; newer edits stay in their own session.

### Review preparation without opening native work

Choose **Prepared work** in the sidebar to see nonempty saved drafts, queued instructions and pending-start reviews across projects. Filter by folder or include locally archived sessions. **Review draft** opens its local Work/Plan editor even when that project folder is missing; the active conversation and its draft stay selected. **Save draft locally** is explicit. A revision conflict keeps your editor and offers **Keep mine and save** or **Load saved draft**.

Queued text is read-only in this overview. **Use in draft** offers **Append to draft** or **Replace draft text**; the queue remains unchanged and reuse is unsaved until you choose Save. **Copy draft text** copies the current reviewed text. **Open conversation** is separate and needs an available native project; it runs no task until you use the normal task controls. Pending starts remain captured review entries, not a new send opportunity.

## Organize active and recent work

The sidebar groups saved Desk sessions by project. **Active** keeps running tasks and approval requests visible; **Recent** holds idle conversations. **Find saved titles or folders** filters local titles or project folders without changing your current conversation.

**Archive session** hides an idle Desk entry from Recent, preserving its native history, provider binding, drafts and prepared follow-ups. **Show archived** → **Restore** returns it to the project list. An archived task that is still running stays in Active so you can approve or stop it. Returning through native history reuses and restores the original binding.

## Read delegated work without coordination clutter

Native sub-agent activity appears in one collapsed **Sub-agents** group per turn. Your prompts and Codex replies stay visible while the native lifecycle rows remain available on expansion. The group stays closed during work unless you open it; streaming updates and state refresh preserve your choice.

Expanded entries show reported agent paths/IDs, lifecycle events, models, prompts and legacy receiver states/results. The same visible collaboration evidence is included in the editable handoff. Native child completion and usage updates keep their own thread scope; they do not finish the parent task or replace its usage. Child approval requests retain their original native request IDs.

## Prepared follow-ups

Write a task, choose **Work** or **Plan**, then click **Save as follow-up**. This saves preparation for the current Desk conversation and provider, even while another task runs. Expand **Prepared follow-ups** to edit, remove, reorder or clear the saved instructions.

While editing a follow-up, choose **Save changes** or **Cancel edit** before editing another row.

When the current turn finishes, choose **Send next**. It submits one reviewed saved instruction to this conversation, not whichever project you select while its response arrives. Remaining instructions stay paused. Opening a page or restarting Desk never sends a queued task.

If a start cannot be confirmed, the queue shows its captured instruction. Check the conversation activity, then choose **It started — record accepted** or **It did not start — keep prepared**. Pending starts block another send; edits made after a start was captured remain prepared instead of being deleted by its receipt.

## Maintain a retained API profile

Choose **Provider settings** → **Manage API profiles** → **Edit profile** to correct a Desk-created endpoint/model or rotate its key. The profile name and saved thread bindings stay unchanged. Leave the key blank to retain its saved value. Current Codex settings and custom native profile files remain read-only in this form.

Saving does not reconfigure a running native backend. If the profile is already loaded, stop Desk and relaunch it to load the new settings there; the form reports this after saving. New native sessions use the updated profile.

## When changing provider

[Step-by-step provider-switch task guide](https://blucca.github.io/guides/switch-codex-api-provider/): verify the local API profile, review the saved evidence, run one next task, and return to the new conversation.

Choose **Continue with another provider** in an open session, or **Review handoff** beside a saved conversation. Review the visible messages, commands, file changes and MCP results; state the next goal and select the target profile. Desk starts a **distinct native thread** with that reviewed text, leaving the original rollout intact. Reading a handoff does not run a model turn or attempt compaction through the old provider. Encrypted reasoning is not replayed into the new thread. Pending commands retain their reported status; an unreported exit or output is shown as unreported, so you can review that evidence before continuing.

Canceling the handoff retains that source’s edited goal and evidence for this page; reviewing another source keeps its preparation separate. A successful start clears the exact submitted edits.

This is useful when the old provider is unavailable and you want to carry useful task evidence into a fresh conversation. Verify the target profile’s endpoint/model in **Open a project** before selecting its name in the handoff. Same-thread resume uses the current selected settings.

<a name="current-vertical-slice"></a>

## Daily workbench

- Project-grouped active/recent sessions, local title/folder filtering and reversible archives.
- Explicit recent-native-history indexing and literal recall across readable cached activity, drafts and prepared follow-ups; read original native evidence before choosing same-thread continuation.
- Named project sessions, saved native history and same-thread reopen.
- Retained API profile editing and key rotation without changing profile or session identity.
- Native tasks, command/file approvals, questions, interruption and Work/Plan modes.
- Readable assistant messages with headings, lists, links and local copyable code blocks.
- Compact, expandable native command/file/MCP evidence. Live calls open automatically; your deliberate expansion or collapse survives output updates.
- Background project approval/completion status, active-task browser title and latest cumulative native thread usage. Latest request input and the reported model context window are displayed separately.
- Native retry/final-failure cards with error codes, HTTP details and practical recovery actions; earlier task/tool output stays visible.
- New output follows when you are already at the bottom; reading older results keeps your place. **Latest output ↓** returns to the next-task box.
- Ordered session-bound follow-ups with explicit Send next, revisioned editing and restart-safe receipt review.
- Project-bound unsent text and Work/Plan drafts saved in the private local database, restored after page or Desk restart.
- Reviewed provider handoffs with visible tool evidence; media/resource descriptors without external fetching.

The ordinary workbench owns its app-server processes. Closing the browser leaves its backend task running; stopping the Desk server terminates its owned app-servers. An already-running Desktop backend is inspected separately below.




## Inspect an already-running backend

On Linux, an existing native control socket can be inspected separately from the desktop renderer:

```sh
python3 -m pip install ".[control]"
python3 -m codex_desk.inspect_running --sock /path/to/app-server-control.sock
```

This reports loaded thread IDs/status, providers and working directories through `thread/loaded/list` and metadata-only `thread/read`. It performs no start/resume/interrupt operation. The native **Unix control socket uses WebSocket framing**. `codex app-server proxy` forwards raw bytes; it does not turn plain newline JSON into a WebSocket connection. The inspector performs that handshake using the optional `websockets` dependency. The ordinary workbench uses native stdio and needs no WebSocket package.
