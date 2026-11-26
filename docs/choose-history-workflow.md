# Choose a workflow for your saved coding-agent work

Start with the job you need to finish, rather than installing another history tool.

| Your next job | Start here |
| --- | --- |
| Continue a known Codex conversation in your terminal | The built-in `codex resume` picker. Use `codex resume --all` to include other project folders, or `codex resume <SESSION_ID>` for a known UUID. |
| Search and analyze histories from several coding agents | [AgentsView](https://github.com/kenn-io/agentsview) provides a local session archive, transcript search and usage reports. [Agent Sessions](https://github.com/jazzyalex/agent-sessions) provides a native macOS history browser with search and supported CLI resume. |
| Let a coding agent retrieve past work or carry context between agents | [deja-vu](https://github.com/vshulcz/deja-vu) indexes existing transcripts and offers CLI/TUI search, MCP memory and cross-agent handoff. |
| Read a past Codex answer, then prepare the next task and return to it in a browser workbench | **Codex Desk**: explicit recent-history indexing, original-conversation reading, same-thread continuation, saved Work/Plan drafts and ordered follow-ups. |

## If the terminal already does the job

From the project folder, run:

```sh
codex resume
```

For a conversation from another folder:

```sh
codex resume --all
```

These are native Codex commands; no Desk installation is needed. See the [official CLI reference](https://developers.openai.com/codex/cli/reference) and `codex resume --help` for your installed version.

## When to try Desk

Suppose you remember a retry decision but not its conversation title, and want to prepare the next checkout test after reading what was decided.

1. **Find the evidence.** Explicitly index recent native history, search a literal phrase, and read the original matching answer or command result. Reading leaves your current task and draft in place.
2. **Prepare the next step.** Continue that same native conversation from its existing project folder. Write an unsent Work or Plan draft, or save ordered follow-ups. Send when ready.
3. **Return to the preparation.** Reload the page, or stop and relaunch Desk with the same state directory. The saved conversation, draft and follow-ups are still there.

[Try that loop in the browser sample](https://blucca.github.io/codex-desk/demo/) with three synthetic histories, then [install Desk](../README.md#install-the-preview) for your own work. The sample saves preparation in browser storage; an installed Desk saves it in local SQLite.

Desk's content index covers a bounded recent window: 200 conversations per pass by default, with coverage and text limits visible in the UI. [The answer-search guide](find-past-answer.md) explains older title browsing, original reading and the full return workflow.

Launch this separate local workbench from the terminal with your installed Codex CLI and current configuration. Desk runs its own app-server.
