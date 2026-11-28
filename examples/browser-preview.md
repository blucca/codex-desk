# Codex Desk browser sample

[Try the hosted sample](https://blucca.github.io/codex-desk/demo/) · [Install Desk for your own history](../README.md#install-the-preview)

## Find one earlier investigation

The sample uses four synthetic histories. Choose **Find a decision in past work**, explicitly index the sample history, then search `retry budget`. Read the checkout task’s response and its `printf sample-checkout` command result. Decide which check that evidence changes or avoids. [First-task guide](../docs/find-past-answer.md).

Optional: continue the sample conversation, keep an unsent Plan or paused follow-up, and reload to return. Preparation stays in this browser. The **Reset sample** control clears the sample’s own saved work. [Workflow reference](../docs/workbench.md) · [Quote and return to original evidence](../docs/evidence-preparation.md).

## Build locally

From the source checkout with Python 3.11+:

```sh
python3 examples/build_browser_preview.py --out temp/browser-preview/demo
python3 -m http.server 8000 --directory temp/browser-preview/demo
```

Open `http://127.0.0.1:8000/`. The builder copies the maintained runtime assets and adds labeled sample history, route-relative assets and installation actions.

For an embedded host, build with `--embedded --out temp/browser-preview/embedded`. The embedding page and its iframe use the same labeled sample and browser-local preparation. The production installer remains the route to your actual local Codex history.
