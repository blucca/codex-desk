# Codex Desk

A local project workbench for native Codex: reopen a project, continue its actual conversation, and see the provider, command results, failures and native usage together.

## Development preview

Requires Python 3.11+ and an existing complete Codex CLI installation. The current native integration was exercised with CLI **0.171.0 on Linux**.

```sh
python3 -m pip install .
codex-desk
```

Or run from source without installation:

```sh
python3 -m codex_desk.server
```

The server prints `http://127.0.0.1:8787` and opens it in your browser. Select an existing project folder and either your current Codex settings or a provider-only `NAME.config.toml` in your Codex home. Run a task. Close the browser, reopen it, and continue the same native conversation. Restarting Desk reattaches completed native conversations; native Codex only writes an unused blank thread's rollout after its first turn, so an unused blank workspace may get a fresh thread on reopening.

```sh
codex-desk --codex /path/to/codex --no-browser
codex-desk --codex-home /your/codex-home --state-dir /your/desk-state
```

Keys remain in your existing Codex configuration or inherited process environment. For a Trial sidecar using `ONRAMP_API_KEY`, launch Desk from the shell where that variable is set. Desk does not ask for, upload or export keys, and does not rewrite your main config, auth or native rollouts. Main MCP, trust and sandbox settings are inherited.

The workbench saves project/profile/native-thread bindings and activity in a local SQLite file (`~/.local/state/codex-desk/desk.sqlite3` by default). Activity includes your task text and local command output. It is not sent to a hosted Desk service.

## Current vertical slice

- Project-bound provider choice and persistent workspace list.
- Native `thread/start`, `thread/resume`, `turn/start` and interruption.
- Live native task, command, answer, failure and usage events.
- One-time native command/file-change approval decisions.
- Last reported cumulative thread usage; cached input is not added to total input.

Dedicated MCP forms and native user-question interactions, importing preexisting sessions, provider editing, model catalogs, cross-provider handoff and platform packaging remain implementation work. Unsupported native interactions have an explicit stop path. Closing the **browser** does not stop its backend task; stopping the **Desk server** terminates its owned app-server processes. This preview does not attach to an already-running desktop backend.

No telemetry, provider account signup or affiliate routing is included in this development preview.

## Check

```sh
DESK_TEST_TEMP=/your/workspace/temp python3 -m unittest discover -s tests -v
```

The native owned-project check ran these two tests through an actual Codex command (exit 0), stopped/restarted Desk, and resumed the same used native thread with its prior turn. Main config/auth remained unchanged. Outside-user trial and repeated use are the next acceptance paths.

## License

MIT. Independent client for the installed Codex app-server protocol.
