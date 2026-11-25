# Codex Desk

A local project workbench for native Codex: reopen a project, continue its actual conversation, and see the provider, command results, failures and native usage together.

![Native MCP results in Codex Desk](docs/workflow.png)

*Own synthetic MCP example: text and structured results, a deliberate tool failure, and the reopened conversation.*

<a name="development-preview"></a>

## Install the preview

Requires Python 3.11+ and an existing complete Codex CLI installation. [Install and sign in to Codex CLI](https://developers.openai.com/codex/cli) first, then check `codex --version` in the shell you will use for Desk. The current native integration was exercised with CLI **0.171.0 on Linux**.

**Linux/macOS/WSL:**

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install https://github.com/blucca/codex-desk/releases/download/v0.1.0a7/codex_desk-0.1.0a7-py3-none-any.whl
codex-desk
```

**Windows PowerShell** (run the virtual environment directly):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install https://github.com/blucca/codex-desk/releases/download/v0.1.0a7/codex_desk-0.1.0a7-py3-none-any.whl
.\.venv\Scripts\codex-desk.exe
```

The release wheel installs without Git. To run from a downloaded or cloned source directory:

```sh
python3 -m codex_desk.server
```

The server prints `http://127.0.0.1:8787` and opens it in your browser. Choose **Open a project**, enter its folder, and select your current Codex settings or a retained provider profile. **Find existing sessions** lists the saved conversations for that project: resume the one you want, or explicitly **Start new conversation**. You can also browse all native history from the sidebar.

Use **Add API provider** to save a provider profile from your existing API key, base URL and model. Native file profiles have distinct IDs from current settings, including a file named `default`. Restarting Desk resumes saved conversations; native Codex writes a blank thread's rollout after its first turn, so an unused blank workspace may get a fresh thread on reopening.

```sh
codex-desk --codex /path/to/codex --no-browser
codex-desk --codex-home /your/codex-home --state-dir /your/desk-state
```

`--codex` accepts an executable on `PATH`, an absolute path, or a relative path from the shell where Desk starts (including `~/...`). Desk checks the executable before opening the browser and uses that same launcher in every selected project.

Existing keys remain in your Codex configuration or inherited process environment. A newly added key is stored in a local provider sidecar with mode 0600 on Linux. Provider overrides go to the app-server through its private stdin protocol, keeping keys out of process command arguments. For a Trial sidecar using `ONRAMP_API_KEY`, launch Desk from the shell where that variable is set. The optional local provider form accepts your existing key without uploading or exporting it. Desk does not rewrite your main config, auth or native rollouts. Main MCP, trust and sandbox settings are inherited.

The workbench saves project/profile/native-thread bindings and activity in a local SQLite file (`~/.local/state/codex-desk/desk.sqlite3` by default). Activity includes your task text and local command output. It is not sent to a hosted Desk service.

## Bring your existing work

1. Choose **Open a project** → enter your project folder → **Find existing sessions**. Keep **Current Codex settings** for the first resume.
2. Resume your saved conversation. Check its prior messages, command output and tool results before sending anything.
3. Give it one small next task, such as “Find this project's verification command, run it, and report the exact pass/failure result. Do not edit files.” Approve the native command if asked.
4. Close the browser. While the Desk terminal is still running, return to its printed URL and choose the same named session. To stop Desk, press `Ctrl+C` in that terminal; this also stops its running native tasks. Next time, launch Desk with the same virtual environment and Codex home/state-directory settings, then choose that session.

For a fresh task, choose **Start new conversation** instead of resuming an existing one.

### When changing provider

Choose **Continue with another provider** in an open session, or **Review handoff** beside a saved conversation. Review the visible messages, commands, file changes and MCP results; state the next goal and select the target profile. Desk starts a **distinct native thread** with that reviewed text, leaving the original rollout intact. Reading a handoff does not run a model turn or attempt compaction through the old provider. Encrypted reasoning is not replayed into the new thread.

This is useful when the old provider is unavailable and you want to carry useful task evidence into a fresh conversation. The target profile must name the endpoint/model you intend to use. Same-thread resume uses the current selected settings.

<a name="current-vertical-slice"></a>

## Daily workbench

- Named project sessions, saved native history and same-thread reopen.
- Native tasks, command/file approvals, questions, interruption and Work/Plan modes.
- Live command output, edits, MCP text/structured results, failures and latest cumulative native thread usage.
- Project-bound unsent drafts while switching sessions in the page.
- Reviewed provider handoffs with visible tool evidence; media/resource descriptors without external fetching.

The ordinary workbench owns its app-server processes. Closing the browser leaves its backend task running; stopping the Desk server terminates its owned app-servers. An already-running Desktop backend is inspected separately below.

Provider choice stays with you. The Add Provider form includes optional, explicitly labeled CometAPI and 88API affiliate account links; using them can earn Blucca a commission.

## Feedback

If you already switch between enterprise/personal providers or lose the desktop UI while local tasks continue, [open an issue](https://github.com/blucca/codex-desk/issues) with your CLI version, operating system and the workflow you wanted to complete. We can work through one project task or handoff with you.

## Check

```sh
DESK_TEST_TEMP=/your/workspace/temp python3 -m unittest discover -s tests -v
```

**32 focused tests pass.** Native CLI 0.171.0 on Linux completed an owned-project command, resumed the same used thread after restart, and ran a reviewed handoff in a distinct thread. Actual native rename/restart, provider selection and a browser-answered planning question were also exercised. Main configuration/auth and the source conversation remained intact.

A real MCP acceptance turn called a local read-only fixture twice: success with a structured result, then a deliberate failure. After restarting Desk, the same native thread showed both results in the browser and reviewed handoff without another inference turn. Controlled browser fixtures additionally cover dynamic-tool results, resource/media descriptors, progress preservation and 390px layout. The fixtures use synthetic data; an outside user's completed project task and return are recorded separately from these checks.

The optional browser regression checks use controlled two-project responses, with no provider calls:

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_navigation.py
DESK_TEST_TEMP=/your/workspace/temp python3 tests/browser_onboarding.py
```

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
