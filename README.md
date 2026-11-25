# Codex Desk

A local project workbench for native Codex: reopen a project, continue its actual conversation, and see the provider, command results, failures and native usage together.

![Native MCP results in Codex Desk](docs/workflow.png)

*Own synthetic MCP example: text and structured results, a deliberate tool failure, and the reopened conversation.*

<a name="development-preview"></a>

## Install the preview

[90-second illustrated project walkthrough](docs/task-walkthrough.md) · [中文：打开第一个项目并继续已有会话](docs/first-project.zh-CN.md)

Requires Python 3.11+ and an existing complete Codex CLI installation. [Install and sign in to Codex CLI](https://developers.openai.com/codex/cli) first, then check `codex --version` in the shell you will use for Desk. The current native integration was exercised with CLI **0.171.0 on Linux**.

**Linux/macOS/WSL:**

```sh
mkdir -p "$HOME/codex-desk-install"
cd "$HOME/codex-desk-install"
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install https://github.com/blucca/codex-desk/releases/download/v0.1.0a13/codex_desk-0.1.0a13-py3-none-any.whl
codex-desk
```

**Windows PowerShell** (run the virtual environment directly):

```powershell
New-Item -ItemType Directory -Force "$HOME\codex-desk-install" | Out-Null
Set-Location "$HOME\codex-desk-install"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install https://github.com/blucca/codex-desk/releases/download/v0.1.0a13/codex_desk-0.1.0a13-py3-none-any.whl
.\.venv\Scripts\codex-desk.exe
```

The release wheel installs without Git. To run from a downloaded or cloned source directory:

```sh
python3 -m codex_desk.server
```

The server prints `http://127.0.0.1:8787` and opens it in your browser. Choose **Open a project**, enter its folder, and select your current Codex settings or a retained provider profile. **Find existing sessions** lists the saved conversations for that project: resume the one you want, or explicitly **Start new conversation**. You can also browse all native history from the sidebar.

Use **Add API provider** to save a provider profile from your existing API key, base URL and model. Native file profiles have distinct IDs from current settings, including a file named `default`. Restarting Desk resumes saved conversations; native Codex writes a blank thread's rollout after its first turn, so a newly created, never-used blank workspace may get a fresh thread on reopening. Saved/imported conversations keep their binding when history is missing; restore the history or relaunch with its original `--codex-home`, or explicitly start new work. Older Desk bindings are kept rather than guessed to be blank.

```sh
codex-desk --codex /path/to/codex --no-browser
codex-desk --codex-home /your/codex-home --state-dir /your/desk-state
```

`--codex` accepts an executable on `PATH`, an absolute path, or a relative path from the shell where Desk starts (including `~/...`). Desk checks the resolved launcher with `--version` before creating state or opening the browser (10-second limit), then uses that same launcher in every selected project. If the check fails, run the printed command in the same shell to see Codex’s native diagnosis and complete or repair that installation.

Existing keys remain in your Codex configuration or inherited process environment. A newly added key is stored in a local provider sidecar with mode 0600 on Linux. Provider overrides go to the app-server through its private stdin protocol, keeping keys out of process command arguments. For a Trial sidecar using `ONRAMP_API_KEY`, launch Desk from the shell where that variable is set. The optional local provider form accepts your existing key without uploading or exporting it. Desk does not rewrite your main config, auth or native rollouts. Main MCP, trust and sandbox settings are inherited.

The [native launcher/profile smoke](https://github.com/blucca/codex-desk/actions/runs/45624593694) passes on actual Ubuntu, Windows and macOS runners with **Python3.11, Node22 and Codex0.171.0**. It exercises the installed native launcher, two blank native thread creations, current settings versus a sidecar named `default`, a project path with spaces, and unchanged configuration/auth. These are metadata-only operations with no model turns.

The workbench saves project/profile/native-thread bindings and activity in a local SQLite file (`~/.local/state/codex-desk/desk.sqlite3` by default). Activity includes your task text and local command output. It is not sent to a hosted Desk service.

## Bring your existing work

1. Choose **Open a project** → enter your project folder → **Find existing sessions**. Keep **Current Codex settings** for the first resume.
2. Resume your saved conversation. Check its prior messages, command output and tool results before sending anything.
3. Give it one small next task, such as “Find this project's verification command, run it, and report the exact pass/failure result. Do not edit files.” Approve the native command if asked.
4. Close the browser. While the Desk terminal is still running, return to its printed URL and choose the same named session. To stop Desk, press `Ctrl+C` in that terminal; this also stops its running native tasks. Next time, launch Desk with the same virtual environment and Codex home/state-directory settings, then choose that session.

For a fresh task, choose **Start new conversation** instead of resuming an existing one.

### Find a saved conversation by title

In **Open a project**, enter part of a conversation title in **Search conversation titles**, then click **Find existing sessions** or press Enter. For conversations from other projects, open **Browse existing Codex sessions** in the sidebar, enter the title text and click **Search titles**.

Project results match the conversation's exact saved working directory (`cwd`): a session started in a subfolder requires that folder or the global browser. Global browsing uses the selected Codex home. Search matches native extracted titles, not message text, command output or MCP results.

Editing the query clears old results and pagination; submit it again to search. Leave the title field blank to list conversations in that scope. **Load more** continues the same submitted title query and scope.

### Prepare a task and come back later

Write your next task and select Work or Plan. **Draft saved locally** confirms the text and mode are saved for this specific Desk session. Reopen the page or restart Desk with the same state directory to recover them; restoration does not send a task. A failed task submission keeps its preparation.

If another tab changes the same draft, choose **Keep this tab draft** or **Load saved draft** before saving or sending again. Sending clears only the preparation actually accepted; newer edits stay in their own session.

### Organize active and recent work

The sidebar groups saved Desk sessions by project. **Active** keeps running tasks and approval requests visible; **Recent** holds idle conversations. **Find saved work** filters local titles or project folders without changing your current conversation.

**Archive session** hides an idle Desk entry from Recent, preserving its native history, provider binding, drafts and prepared follow-ups. **Show archived** → **Restore** returns it to the project list. An archived task that is still running stays in Active so you can approve or stop it. Returning through native history reuses and restores the original binding.

### Prepared follow-ups

Write a task, choose **Work** or **Plan**, then click **Save as follow-up**. This saves preparation for the current Desk conversation and provider, even while another task runs. Expand **Prepared follow-ups** to edit, remove, reorder or clear the saved instructions.

When the current turn finishes, choose **Send next**. It submits one reviewed saved instruction to this conversation, not whichever project you select while its response arrives. Remaining instructions stay paused. Opening a page or restarting Desk never sends a queued task.

If a start cannot be confirmed, the queue shows its captured instruction. Check the conversation activity, then choose **It started — record accepted** or **It did not start — keep prepared**. Pending starts block another send; edits made after a start was captured remain prepared instead of being deleted by its receipt.

### Maintain a retained API profile

Choose **Manage API profiles** → **Edit profile** to correct a Desk-created endpoint/model or rotate its key. The profile name and saved thread bindings stay unchanged. Leave the key blank to retain its saved value. Current Codex settings and custom native profile files remain read-only in this form.

Saving does not reconfigure a running native backend. If the profile is already loaded, stop Desk and relaunch it to load the new settings there; the form reports this after saving. New native sessions use the updated profile.

### When changing provider

[Step-by-step provider-switch task guide](https://blucca.github.io/guides/switch-codex-api-provider/): verify the local API profile, review the saved evidence, run one next task, and return to the new conversation.

Choose **Continue with another provider** in an open session, or **Review handoff** beside a saved conversation. Review the visible messages, commands, file changes and MCP results; state the next goal and select the target profile. Desk starts a **distinct native thread** with that reviewed text, leaving the original rollout intact. Reading a handoff does not run a model turn or attempt compaction through the old provider. Encrypted reasoning is not replayed into the new thread.

This is useful when the old provider is unavailable and you want to carry useful task evidence into a fresh conversation. Verify the target profile’s endpoint/model in **Open a project** before selecting its name in the handoff. Same-thread resume uses the current selected settings.

<a name="current-vertical-slice"></a>

## Daily workbench

- Project-grouped active/recent sessions, local title/folder filtering and reversible archives.
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

Provider choice stays with you. The Add Provider form includes optional, explicitly labeled CometAPI and 88API affiliate account links; using them can earn Blucca a commission.

## Feedback

If you already switch between enterprise/personal providers or lose the desktop UI while local tasks continue, [ask for task help](https://github.com/blucca/codex-desk/issues/new?template=task-help.yml) with your CLI version, operating system, the one workflow you want to complete and the step you reached. We can work through one project task or handoff with you.

## Check

Startup tests cover a broken npm launcher, a missing interpreter and a bounded version-check timeout before any Desk state or browser opens. Launcher output is suppressed; diagnostics give the exact same-shell command.

```sh
DESK_TEST_TEMP=/your/workspace/temp python3 -m unittest discover -s tests -v
```

**108 focused tests pass.** Native CLI 0.171.0 on Linux completed an owned-project command, resumed the same used thread after restart, and ran a reviewed handoff in a distinct thread. Actual native rename/restart, provider selection and a browser-answered planning question were also exercised. Main configuration/auth and the source conversation remained intact.

Two browser windows importing the same saved thread and profile now share one complete local binding. A slow native history read leaves other open sessions responsive. A separate controlled native-stdio/HTTP fixture exercises retained-profile import, same-thread continuation, reviewed distinct-provider handoff and Desk restart without provider calls. Project organization, prepared follow-up and native state browser checks exercise session scope, explicit admission/review, restart and 390/1250 layouts. Profile edit and draft browser checks exercise local persistence, canceled/delayed responses, two-tab draft conflicts and 390/1280 layouts.

A real MCP acceptance turn called a local read-only fixture twice: success with a structured result, then a deliberate failure. After restarting Desk, the same native thread showed both results in the browser and reviewed handoff without another inference turn. Controlled browser fixtures additionally cover dynamic-tool results, resource/media descriptors, progress preservation and 390px layout. The fixtures use synthetic data; an outside user's completed project task and return are recorded separately from these checks.

The optional browser regression checks use controlled two-project responses, with no provider calls:

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_navigation.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_onboarding.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_search.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_activity.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_monitor.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_errors.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_profiles.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_drafts.py
```

The dialog-error check exercises real loopback failures for a duplicate provider name, a missing handoff folder and a missing saved project. Errors remain visible in the open dialog, provider retry keeps nonsecret inputs, and cancel clears the key. The missing-history tests preserve an imported thread through failure/restart and resume it after restoration, without creating a replacement.

The activity-reader check replays three synthetic turns through the loopback UI: safe Markdown, exact copyable code, complete collapsible tool evidence, live/manual expansion, final-result replacement and message ordering. The monitor check covers another project requesting approval and finishing while the selected conversation is quiet, reading-position preservation and following fresh output. Backend HTTP fixtures cover approval/completion races and concurrent task submissions from two browser tabs.

The title-search check covers project/global title filters, query-bound pagination, stale search/page/dialog/handoff responses and provider retention. Metadata-only search against actual owned Codex CLI 0.163.0 history included the matching saved thread, excluded an unmatched title and preserved exact cwd filtering, with no thread start/read/resume or model turn.

The onboarding check covers project-filtered native history, explicit existing/new choice, failed catalog recovery and stale folder/dialog responses. The navigation check covers a slow older open, rapid duplicate submission, switching projects while a turn/approval response is pending, unsent drafts, and retrying a failed open. Set `DESK_CHROMIUM` to use an existing Chromium executable.

## License

MIT. Independent client for the installed Codex app-server protocol.

## Inspect an already-running backend

On Linux, an existing native control socket can be inspected separately from the desktop renderer:

```sh
python3 -m pip install ".[control]"
python3 -m codex_desk.inspect_running --sock /path/to/app-server-control.sock
```

This reports loaded thread IDs/status, providers and working directories through `thread/loaded/list` and metadata-only `thread/read`. It performs no start/resume/interrupt operation. The native **Unix control socket uses WebSocket framing**. `codex app-server proxy` forwards raw bytes; it does not turn plain newline JSON into a WebSocket connection. The inspector performs that handshake using the optional `websockets` dependency. The ordinary workbench uses native stdio and needs no WebSocket package.
