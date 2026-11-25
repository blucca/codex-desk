# Codex Desk

A local project workbench for native Codex: reopen a project, continue its actual conversation, and see the provider, command results, failures and native usage together.

## Development preview

Requires Python 3.11+ and an existing complete Codex CLI installation. [Install and sign in to Codex CLI](https://developers.openai.com/codex/cli) first, then check `codex --version` in the shell you will use for Desk. The current native integration was exercised with CLI **0.171.0 on Linux**.

**Linux/macOS/WSL:**

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install git+https://github.com/blucca/codex-desk.git@v0.1.0a6
codex-desk
```

**Windows PowerShell** (run the virtual environment directly):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install git+https://github.com/blucca/codex-desk.git@v0.1.0a6
.\.venv\Scripts\codex-desk.exe
```

Or run from source without installation:

```sh
python3 -m codex_desk.server
```

The server prints `http://127.0.0.1:8787` and opens it in your browser. Select an existing project folder and either your current Codex settings or a provider-only `NAME.config.toml` in your Codex home. Native file profiles have distinct IDs from current settings, including a file profile named `default`; older stored profile names remain readable. Use **Add API provider** to save a new provider profile from your existing API key, base URL and model. Run a task. Close the browser, reopen it, and continue the same native conversation. Restarting Desk reattaches completed native conversations; native Codex only writes an unused blank thread's rollout after its first turn, so an unused blank workspace may get a fresh thread on reopening.

```sh
codex-desk --codex /path/to/codex --no-browser
codex-desk --codex-home /your/codex-home --state-dir /your/desk-state
```

`--codex` accepts an executable on `PATH`, an absolute path, or a relative path from the shell where Desk starts (including `~/...`). Desk checks the executable before opening the browser and uses that same launcher in every selected project.

Existing keys remain in your Codex configuration or inherited process environment. A newly added key is stored in a local provider sidecar with mode 0600 on Linux. Provider overrides go to the app-server through its private stdin protocol, keeping keys out of process command arguments. For a Trial sidecar using `ONRAMP_API_KEY`, launch Desk from the shell where that variable is set. The optional local provider form accepts your existing key without uploading or exporting it. Desk does not rewrite your main config, auth or native rollouts. Main MCP, trust and sandbox settings are inherited.

The workbench saves project/profile/native-thread bindings and activity in a local SQLite file (`~/.local/state/codex-desk/desk.sqlite3` by default). Activity includes your task text and local command output. It is not sent to a hosted Desk service.

## First project loop

1. Open a project you already work on. Keep **Current Codex settings** for the first task.
2. Ask: “Find this project's verification command, run it, and report the exact pass/failure result. Do not edit files.” Approve the native command if asked.
3. Close the browser. Reopen Desk and the same named session: the command, output and conversation are still there. Give it your next project task.
4. For an intentional provider switch, choose **Continue with another provider**. Review the actual tool evidence, write the next goal, and select your other profile. This starts a separate native thread; it leaves the original conversation intact.

Already use MCP tools in Codex? Desk inherits those settings and shows their text/structured results and failures. Tool evidence is included in the reviewed handoff; media and embedded resources are represented without fetching external content.

## Current vertical slice

- Project-bound provider choice and persistent, named workspace list; importing the same native conversation/profile reopens its existing workspace.
- First-task titles and editable session names, synced through native `thread/name/set` for saved conversations. Blank-workspace names stay local until the first turn persists.
- Native `thread/start`, `thread/resume`, `turn/start` and interruption. Failed opens can be retried with the existing native thread/profile.
- Project-isolated unsent task drafts while navigating within the page; a late response from another session leaves the current draft and approvals intact. Drafts live in page memory until submitted or the page is closed.
- Live native task, command, answer, failure and usage events.
- Readable MCP calls, arguments, progress, text/structured results and failures; imported dynamic-tool evidence.
- Media/resource descriptors instead of expanded binary payloads; application-private MCP metadata is excluded from the handoff.
- One-time native command/file-change approval decisions.
- Native questions with selectable answers or private text input.
- Work/Plan mode choice with the native planning protocol; mode selection survives reload and Work explicitly exits a previous Plan mode.
- Browse and read existing native history, including actual command output and exits.
- Review/edit a visible-evidence handoff, choose an existing provider profile, and start a new native conversation with an explicit next task.
- Last reported cumulative thread usage; cached input is not added to total input.

Dedicated MCP forms, provider editing, model catalogs and platform packaging remain implementation work. Existing history resumes with the current selected Codex settings; a handoff starts a distinct native thread using the chosen profile. Unsupported native interactions have an explicit stop path. Closing the **browser** does not stop its backend task; stopping the **Desk server** terminates its owned app-server processes. This preview does not attach to an already-running desktop backend.

Provider choice stays with you. The Add Provider form includes optional, explicitly labeled CometAPI and 88API affiliate account links; using them can earn Blucca a commission. The client uses the profile you select.

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
```

They cover a slow older open, rapid duplicate submission, switching projects while a turn/approval response is pending, unsent drafts, and retrying a failed open. Set `DESK_CHROMIUM` to use an existing Chromium executable.

## License

MIT. Independent client for the installed Codex app-server protocol.

## Inspect an already-running backend

On Linux, an existing native control socket can be inspected separately from the desktop renderer:

```sh
python3 -m pip install ".[control]"
python3 -m codex_desk.inspect_running --sock /path/to/app-server-control.sock
```

This reports loaded thread IDs/status, providers and working directories through `thread/loaded/list` and metadata-only `thread/read`. It performs no start/resume/interrupt operation. The native **Unix control socket uses WebSocket framing**. `codex app-server proxy` forwards raw bytes; it does not turn plain newline JSON into a WebSocket connection. The inspector performs that handshake using the optional `websockets` dependency. The ordinary workbench uses native stdio and needs no WebSocket package.
