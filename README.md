# Codex Desk

**Find a past Codex answer, then pick up the task.** Search your recent local history, read the original conversation, and continue in the same native thread when ready.

![Codex Desk: index local history, find a retry decision, and read the original conversation](docs/find-answer.gif)

*Synthetic checkout example: index local history, search “retry budget”, and read the original answer.*

<a name="development-preview"></a>

## Install the preview

Use your existing [Codex CLI](https://developers.openai.com/codex/cli) installation and sign-in. Check `codex --version` in the terminal where you will launch Desk.

With [uv](https://docs.astral.sh/uv/getting-started/installation/), **one command** installs and opens the free local workbench on Linux, macOS, Windows or WSL:

```sh
uvx --from https://github.com/blucca/codex-desk/releases/download/v0.1.0a28/codex_desk-0.1.0a28-py3-none-any.whl codex-desk
```

Keep that terminal running. Desk opens **http://127.0.0.1:8787** in your browser. Run the same command next time; your saved conversations and drafts remain local.

If that address is already in use, reopen it when your existing Desk terminal is still running. To use a different port, append `--port 8788` to the launch command. An occupied port does not create or change Desk state.

<details>
<summary>Install with Python instead of uv</summary>

Python 3.11+ is required. The wheel has no runtime dependencies.

**Linux/macOS/WSL:**

```sh
mkdir -p "$HOME/codex-desk-install"
cd "$HOME/codex-desk-install"
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install https://github.com/blucca/codex-desk/releases/download/v0.1.0a28/codex_desk-0.1.0a28-py3-none-any.whl
codex-desk
```

**Windows PowerShell:**

```powershell
New-Item -ItemType Directory -Force "$HOME\codex-desk-install" | Out-Null
Set-Location "$HOME\codex-desk-install"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install https://github.com/blucca/codex-desk/releases/download/v0.1.0a28/codex_desk-0.1.0a28-py3-none-any.whl
.\.venv\Scripts\codex-desk.exe
```

For later launches, use `codex-desk` in the activated environment, or `.\.venv\Scripts\codex-desk.exe` in PowerShell.

</details>

## Bring your existing work

1. **Your recent Codex work** appears on the first screen, including the project folder. Click **Resume conversation** to open the one you want.
2. Read the saved messages, command results and tool evidence. Write your next task and wait for **Draft saved locally**, or choose **Save as follow-up**. Send it when ready; Work and Plan modes use native Codex.
3. Close the page and return to the printed URL. Desk reopens your last saved conversation with its unsent draft. After stopping Desk with **Ctrl+C**, relaunch with the same command to return.

![Recent CLI conversations ready to resume in Codex Desk](docs/recent-work.png)

*Example first screen. Listing recent work runs no task; Resume is an explicit choice.*

Know the title? **Browse all conversations** searches native conversation titles across folders. **Open a project** lets you choose an exact folder, another retained profile, or explicitly start a new conversation. For a custom Codex history location, add `--codex-home /your/codex-home` to the launch command.

[中文：打开已有会话并继续工作](docs/first-project.zh-CN.md) · [Illustrated walkthrough](docs/task-walkthrough.md)

## Find an earlier answer

1. Choose **Find a decision in past work** on the first screen, or **Search saved content** in the sidebar.
2. Choose **Index existing Codex history** to read up to **200 recently updated native conversations** into a local cache, including work you have never opened in Desk. Indexing is explicit; it neither opens those conversations nor sends a task.
3. Enter a word or phrase from the answer, command output or tool result, then **Search**. Choose **Read original conversation** on a native result to inspect the matching evidence—even if its project folder has been removed. Your selected task and draft stay unchanged; **Back to search** keeps the query and results.
4. Ready to work on it? Choose **Continue this conversation** to resume the **original native thread** using **Current Codex settings**. Continuing requires the saved project folder to exist. Prepare the next instruction, then send it when ready.

Search is literal, case-insensitive and Unicode-normalized. It also covers Desk-cached activity, drafts and prepared follow-ups. **Index coverage and text limits** shows cached coverage and shortened or omitted text; this is a bounded recent-history cache. Reindexing refreshes the recent window and skips unchanged snapshots. For older conversations beyond that window, browse titles and open the conversation first.

[Short guide: find a past Codex answer and reopen its task](docs/find-past-answer.md)

## Why use Desk?

- **Resume, don't reconstruct.** Reopen the actual saved CLI thread and its prior messages, commands, file changes and MCP results.
- **Keep several projects moving.** Active tasks and approvals stay visible while you read another project's results.
- **Prepare tomorrow's work.** Session-bound drafts and ordered follow-ups persist across page and server restarts. Choose when to send them.
- **Review before changing provider.** Carry editable visible task evidence into a distinct target-provider conversation, preserving the original.
- **Find a saved decision.** Search readable history and inspect the original answer before deciding whether to continue the task.

[Workflow reference: search, profiles, follow-ups, handoffs and usage](docs/workbench.md)

## Local by design

Desk runs on loopback and uses your installed Codex app-server. Existing sign-in, model/provider, MCP, trust and sandbox settings come from your Codex configuration. A new Desk account or API key is unnecessary.

Project bindings, cached activity, indexed native history and drafts live in `~/.local/state/codex-desk/desk.sqlite3`. History indexing and the original-conversation reader use native list/read requests; searching uses the local cache. New provider keys stay in a private local sidecar. Desk keeps your main configuration, auth and original rollouts intact. Native Codex sends model requests to your selected provider when you run a task.

Closing the browser leaves Desk running; **Ctrl+C** stops Desk and its owned native tasks. It runs its own app-server rather than attaching to an already-running Desktop backend.

Other launch options (append to either launcher):

```sh
codex-desk --codex /path/to/codex --no-browser
codex-desk --codex-home /your/codex-home --state-dir /your/desk-state --port 8788
codex-desk --version
```

The native launcher/profile smoke has passed on Ubuntu, Windows and macOS with CLI 0.171.0. Native task/MCP interaction acceptance uses Linux; browser first-use checks exercise desktop and 390px layouts.

## Feedback and development

[Report a bug or ask for workflow help](https://github.com/blucca/codex-desk/issues/new/choose). Tell us the one task you were trying to finish, your OS/CLI version, and where you got stuck. Suggestions and contributions are welcome.

From a source checkout:

```sh
python3 -m codex_desk.server
python3 -m unittest discover -s tests
```

Browser regressions use controlled local HTTP/SQLite, with no provider calls. See [the first-use test](tests/browser_home.py) and [installed daily-workflow CI](.github/workflows/daily-workbench.yml). [Native MCP fixture and result walkthrough](docs/native-mcp-example.md).

## License

MIT.
