# Choose a workflow for your saved coding-agent work

Start with the job you need to finish, rather than installing another history tool.

| Your next job | Start here |
| --- | --- |
| Continue a known Codex conversation in your terminal | The built-in `codex resume` picker. Use `codex resume --all` to include other project folders, or `codex resume <SESSION_ID>` for a known UUID. |
| Browse and switch between Codex chats in your terminal | The native `codex agents` command center. Its documented search covers chat names, prompt previews and working directories. |
| Submit the next instruction to an existing native session's queue | `codex queue --thread <SESSION_ID> --message "Run the remaining checks"`. Add `--resume` to also ask native Codex to resume the target session. |
| Search and analyze histories from several coding agents | [AgentsView](https://github.com/kenn-io/agentsview) provides a local session archive, transcript search and usage reports. [Agent Sessions](https://github.com/jazzyalex/agent-sessions) provides a native macOS history browser with search and supported CLI resume. |
| Let a coding agent retrieve past work or carry context between agents | [deja-vu](https://github.com/vshulcz/deja-vu) indexes existing transcripts and offers CLI/TUI search, MCP memory and cross-agent handoff. |
| Find an earlier issue or decision, inspect its original evidence, and optionally prepare the remaining work in a browser | **Codex Desk**: search reply, command and tool text in explicitly indexed recent history. Read the matching original without disturbing your selected task or draft; continue and save preparation when that helps your next step. |

## If the terminal already does the job

From the project folder, run:

```sh
codex resume
```

For a conversation from another folder:

```sh
codex resume --all
```

To browse and switch chats in the native command center:

```sh
codex agents
```

To submit text to an existing native session's queue:

```sh
codex queue --thread <SESSION_ID> --message "Run the remaining checks"
```

The queue accepts a session UUID or exact name; use a UUID when names repeat. Queued messages use that session's model. Optional `--resume` also asks native Codex to resume the target on its local daemon or selected remote server. Queueing submits an instruction to the **native queue**; Desk's **Save as follow-up** saves preparation that stays paused until you choose **Send next**.

These command shapes are supported by Codex CLI **0.171.0**. Check `codex resume --help`, `codex agents --help` and `codex queue --help` for your installed version. The [official CLI reference](https://developers.openai.com/codex/cli/reference) also documents `/agents` search, prompt-history search and draft-history navigation. No Desk installation is needed for these native workflows.

## When to try Desk

An issue comes back. You remember its identifier or a phrase, but not the conversation title. Before repeating the investigation, find what was already decided and what the command or tool actually reported.

1. **Find the evidence.** Explicitly index recent native history, search the issue ID or literal phrase, and read the matching original answer, command or tool result. Reading leaves your selected task and draft in place.
2. **Decide the remaining work.** Use the original evidence to identify today's next check. If the next task belongs in the old conversation, choose **Continue this conversation** from its existing project folder. If it informs another task you already have open, keep preparing that task instead.
3. **Park preparation when interrupted.** In the conversation you choose to work on, write an unsent Work or Plan draft, or save ordered follow-ups. Reload the page, or stop and relaunch Desk with the same state directory to return to that saved conversation and preparation. Choose when to send it.

[Try the browser sample](https://blucca.github.io/codex-desk/demo/) with three synthetic histories, then [install Desk](../README.md#install-the-preview) for your own work. Finding and reading an answer is useful on its own; continuation and preparation are optional. The sample saves preparation in browser storage; an installed Desk saves it in local SQLite.

Desk's content index covers a bounded recent window: 200 conversations per pass by default, with coverage and text limits visible in the UI. [The answer-search guide](find-past-answer.md) explains older title browsing, original reading and the full return workflow.

Launch this separate local workbench from the terminal with your installed Codex CLI and current configuration. Desk runs its own app-server.

[Find a past answer from your existing macOS Desktop history](find-desktop-answer.macos.md).
