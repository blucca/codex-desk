# Codex Desk

A local project workbench for native Codex: reopen a project, continue its actual conversation, and see the provider, command results, failures and native usage together.

## Development preview

Requires Python 3.11+ and an existing complete Codex CLI installation. The current native integration was exercised with CLI **0.171.0 on Linux**.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install git+https://github.com/blucca/codex-desk.git@v0.1.0a1
codex-desk
```

Or run from source without installation:

```sh
python3 -m codex_desk.server
```

The server prints `http://127.0.0.1:8787` and opens it in your browser. Select an existing project folder and either your current Codex settings or a provider-only `NAME.config.toml` in your Codex home. Use **Add API provider** to save a new provider profile from your existing API key, base URL and model. Run a task. Close the browser, reopen it, and continue the same native conversation. Restarting Desk reattaches completed native conversations; native Codex only writes an unused blank thread's rollout after its first turn, so an unused blank workspace may get a fresh thread on reopening.

```sh
codex-desk --codex /path/to/codex --no-browser
codex-desk --codex-home /your/codex-home --state-dir /your/desk-state
```

Existing keys remain in your Codex configuration or inherited process environment. A newly added key is stored in a local provider sidecar with mode 0600 on Linux. Provider overrides go to the app-server through its private stdin protocol, keeping keys out of process command arguments. For a Trial sidecar using `ONRAMP_API_KEY`, launch Desk from the shell where that variable is set. The optional local provider form accepts your existing key without uploading or exporting it. Desk does not rewrite your main config, auth or native rollouts. Main MCP, trust and sandbox settings are inherited.

The workbench saves project/profile/native-thread bindings and activity in a local SQLite file (`~/.local/state/codex-desk/desk.sqlite3` by default). Activity includes your task text and local command output. It is not sent to a hosted Desk service.

## Current vertical slice

- Project-bound provider choice and persistent workspace list.
- Native `thread/start`, `thread/resume`, `turn/start` and interruption.
- Live native task, command, answer, failure and usage events.
- One-time native command/file-change approval decisions.
- Native questions with selectable answers or private text input.
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

The first native owned-project check ran the two persistence/profile tests through an actual Codex command (exit 0), stopped/restarted Desk, and resumed the same used native thread with its prior turn. A second browser-driven native check read that existing history, previewed its actual command/output, started a new native thread with the reviewed handoff and an explicit next task, and ran all three current tests successfully. The source rollout remained unchanged. Sidecar model/provider selection was also checked through native CLI overrides against an isolated loopback configuration. Main config/auth remained unchanged. The native question response shape and browser choice/private-input flow are checked against the 0.171 schema with a controlled fixture; live model-generated questions remain to be exercised. Outside-user trial and repeated use are the next acceptance paths.

## License

MIT. Independent client for the installed Codex app-server protocol.

## Inspect an already-running backend

On Linux, an existing native control socket can be inspected separately from the desktop renderer:

```sh
python3 -m pip install ".[control]"
python3 -m codex_desk.inspect_running --sock /path/to/app-server-control.sock
```

This reports loaded thread IDs/status, providers and working directories through `thread/loaded/list` and metadata-only `thread/read`. It performs no start/resume/interrupt operation. The native **Unix control socket uses WebSocket framing**. `codex app-server proxy` forwards raw bytes; it does not turn plain newline JSON into a WebSocket connection. The inspector performs that handshake using the optional `websockets` dependency. The ordinary workbench uses native stdio and needs no WebSocket package.
