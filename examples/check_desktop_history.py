#!/usr/bin/env python3
"""Check native history-reader compatibility using isolated synthetic rollouts."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import traceback
from unittest.mock import patch

import codex_desk
from codex_desk.recall import _item_text
from codex_desk.runtime import Runtime
from codex_desk.server import Desk, resolve_codex


PHRASE = "SYNTHETIC_DESK_HISTORY_RECALL"
ALLOWED_REQUESTS = frozenset(("initialize", "thread/list", "thread/read"))
ALLOWED_SENDS = ALLOWED_REQUESTS | {"initialized"}
SCAN_DEADLINE = 45


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def write_fixture(home, project, native_version):
    """Legacy JSONL is a supported native history mode, with no prebuilt DB."""
    home.mkdir(parents=True)
    project.mkdir(parents=True)
    (home / "config.toml").write_text(
        '# Synthetic history-reader fixture; no model tasks.\n'
        'model_provider = "openai"\n'
        'approval_policy = "never"\n'
        'sandbox_mode = "read-only"\n', encoding="utf-8")
    created = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    fixtures = []
    for number, source in enumerate(("vscode", "cli", "exec"), start=1):
        thread_id = f"00000000-0000-4000-8000-{number:012d}"
        turn_id = f"00000000-0000-4000-9000-{number:012d}"
        stamp = created + timedelta(seconds=number)
        timestamp = stamp.isoformat().replace("+00:00", "Z")
        prompt = f"Synthetic {source} history fixture: inspect the saved decision."
        answer = f"Synthetic {source} saved answer: {PHRASE}; retain the original evidence."
        records = [
            ("session_meta", {
                "session_id": thread_id, "id": thread_id, "timestamp": timestamp,
                "cwd": str(project), "runtime_workspace_roots": [str(project)],
                "originator": "codex_desk_synthetic_history_fixture",
                "cli_version": native_version.removeprefix("codex-cli "),
                "source": source, "thread_source": "user", "model_provider": "openai",
                "base_instructions": {"text": "Synthetic local history-reader fixture."},
                "history_mode": "legacy",
            }),
            ("event_msg", {
                "type": "task_started", "turn_id": turn_id, "root_turn_id": turn_id,
                "started_at": int(stamp.timestamp()), "model_context_window": 128000,
                "collaboration_mode_kind": "default",
            }),
            ("response_item", {
                "type": "message", "id": f"synthetic_user_{source}", "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }),
            ("event_msg", {"type": "user_message", "message": prompt,
                           "images": [], "local_images": []}),
            ("response_item", {
                "type": "message", "id": f"synthetic_agent_{source}", "role": "assistant",
                "content": [{"type": "output_text", "text": answer}],
            }),
            ("event_msg", {"type": "agent_message", "message": answer}),
            ("event_msg", {
                "type": "task_complete", "turn_id": turn_id, "root_turn_id": turn_id,
                "last_agent_message": answer, "started_at": int(stamp.timestamp()),
                "completed_at": int(stamp.timestamp()) + 1,
            }),
        ]
        directory = home / "sessions" / stamp.strftime("%Y/%m/%d")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"rollout-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{thread_id}.jsonl"
        path.write_text("".join(json.dumps({"timestamp": timestamp, "type": kind,
                                           "payload": payload}) + "\n"
                                for kind, payload in records), encoding="utf-8")
        fixtures.append({"source": source, "thread_id": thread_id, "turn_id": turn_id,
                         "answer": answer, "path": str(path), "history_mode": "legacy"})
    return fixtures


def run_check(args):
    root = Path(args.work_dir).expanduser()
    require(root.is_absolute(), "--work-dir must be an absolute scratch-directory path")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    binary_path = Path(args.codex).expanduser()
    require(binary_path.is_absolute(), "--codex must be an explicit absolute executable path")
    binary = resolve_codex(str(binary_path))
    checked = subprocess.run([binary, "--version"], capture_output=True, text=True,
                             timeout=10, check=True)
    native_version = checked.stdout.strip()
    require(native_version, "Native --version returned no version")
    work = Path(tempfile.mkdtemp(prefix="desktop-history-", dir=root))
    home, project, state = work / ".codex", work / "project", work / "desk-state"
    fixtures = write_fixture(home, project, native_version)
    protected = {Path(row["path"]): Path(row["path"]).read_bytes() for row in fixtures}
    settings = {home / name: (home / name).read_bytes() if (home / name).exists() else None
                for name in ("config.toml", "auth.json")}
    report = {
        "status": "RUNNING", "scope": "synthetic native saved-history reader compatibility",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "codex_executable": binary, "native_version": native_version,
        "desk_version": codex_desk.__version__, "desk_module": codex_desk.__file__,
        "work_dir": str(work), "codex_home": str(home), "phrase": PHRASE,
        "scan_deadline_seconds": SCAN_DEADLINE, "fixtures": fixtures, "steps": [],
        "model_turns": 0, "imports": 0, "resumes": 0, "new_threads": 0,
    }
    calls, sends, blocked, processes, readers = [], [], [], [], []
    lock = threading.Lock()
    stage = "initialize_and_list"
    desk = None

    class ReadOnlyRuntime(Runtime):
        def send(self, payload):
            method = payload.get("method")
            with lock:
                if self.process not in processes:
                    processes.append(self.process)
                    readers.extend((self.reader, self.stderr_reader))
                if method not in ALLOWED_SENDS:
                    blocked.append(method)
                sends.append(method)
            require(method in ALLOWED_SENDS, f"Blocked native write/task method: {method}")
            return super().send(payload)

        def request(self, method, params, timeout=30):
            require(method in ALLOWED_REQUESTS, f"Blocked native request: {method}")
            entry = {"stage": stage, "method": method, "params": params}
            with lock:
                calls.append(entry)
            try:
                response = super().request(method, params, min(timeout, 15))
                entry["success"] = True
                if method == "thread/list":
                    entry["rows"] = [{"id": row.get("id"), "source": row.get("source"),
                                      "historyMode": row.get("historyMode")}
                                     for row in response.get("data", [])]
                if method == "thread/read":
                    thread = response.get("thread", {})
                    entry.update(thread_id=thread.get("id"), source=thread.get("source"),
                                 turns=len(thread.get("turns", [])))
                return response
            except Exception as error:
                entry.update(success=False, error=str(error))
                raise

    # Runtime receives only this scratch CODEX_HOME; isolate other user/config roots too.
    environment = {"CODEX_HOME": str(home), "HOME": str(work / "user-home"),
                   "USERPROFILE": str(work / "user-home"),
                   "XDG_CONFIG_HOME": str(work / "xdg-config"),
                   "XDG_CACHE_HOME": str(work / "xdg-cache"),
                   "XDG_STATE_HOME": str(work / "xdg-state"),
                   "TMPDIR": str(work / "tmp"), "TMP": str(work / "tmp"),
                   "TEMP": str(work / "tmp")}
    for path in set(environment.values()):
        Path(path).mkdir(parents=True, exist_ok=True)

    def close_desk():
        nonlocal desk
        if desk is not None:
            try:
                desk.close()
            finally:
                desk.store.db.close()
                desk = None

    with patch.dict(os.environ, environment), patch("codex_desk.server.Runtime", ReadOnlyRuntime):
        try:
            desk = Desk(binary, home, state)
            positive = {row["thread_id"]: row for row in fixtures if row["source"] != "exec"}
            negative = next(row for row in fixtures if row["source"] == "exec")
            options = {"limit": 30, "modelProviders": [], "sortKey": "updated_at"}
            listed = desk.catalog().request("thread/list", options)
            rows = listed.get("data", [])
            require({row["id"] for row in rows} == set(positive),
                    f"Default native source visibility differs: {rows}")
            require(all(row.get("source") == positive[row["id"]]["source"] for row in rows),
                    "Default native source mapping differs")
            exec_rows = desk.catalog().request("thread/list", {**options, "sourceKinds": ["exec"]})
            require([row["id"] for row in exec_rows.get("data", [])] == [negative["thread_id"]],
                    "The hidden exec fixture was not discoverable with an explicit exec filter")
            report["source_mapping"] = [
                {"thread_id": row["id"], "native_source": row["source"],
                 "default_visible": row["id"] in positive}
                for row in [*rows, *exec_rows["data"]]]
            report["steps"].append({"step": stage, "default_sources": [row["source"] for row in rows],
                                    "positive_count": len(rows), "exec_hidden": True,
                                    "explicit_exec_count": len(exec_rows["data"])})

            stage = "explicit_index"
            desk.history_scanner.start(200)
            desk.history_scanner.worker.join(SCAN_DEADLINE)
            if desk.history_scanner.worker.is_alive():
                desk.history_scanner.cancel()
                for runtime in list(desk.runtimes.values()):
                    runtime.close()
                raise TimeoutError(f"Native history scan exceeded {SCAN_DEADLINE} seconds")
            job = desk.history_scanner.status()
            report["steps"].append({"step": stage, "job": job,
                                    "coverage": desk.native_index.stats()})
            require(job["status"] == "completed" and job["seen"] == 2
                    and job["indexed"] == 2 and job["failed"] == 0, f"Native index failed: {job}")

            stage = "literal_search_and_original_read"
            found = desk.recall(PHRASE)
            hits = found["results"]
            require(len(hits) == 2 and {hit["thread_id"] for hit in hits} == set(positive),
                    f"Expected two positive phrase hits and no exec hit: {hits}")
            originals = []
            for hit in hits:
                fixture = positive[hit["thread_id"]]
                require(hit["kind"] == "native-activity", "Search returned a non-native hit")
                require(hit["turn_id"] == fixture["turn_id"], "Original turn ID differs")
                thread = desk.history(hit["thread_id"])
                require(thread["id"] == fixture["thread_id"], "Original thread ID differs")
                items = [item for turn in thread["turns"] if turn["id"] == hit["turn_id"]
                         for item in turn["items"] if item["id"] == hit["item_id"]]
                require(len(items) == 1 and items[0].get("text") == fixture["answer"]
                        and PHRASE in _item_text(items[0]),
                        f"Exact original item or synthetic answer differs: {items}")
                originals.append({"source": fixture["source"], "thread_id": thread["id"],
                                  "turn_id": hit["turn_id"], "item_id": hit["item_id"],
                                  "item_type": items[0]["type"], "exact_text": True})
            report["steps"].append({"step": stage, "hits": len(hits), "originals": originals})
            require(not [row for row in desk.store.sessions() if row["id"] != "native-catalog"],
                    "Read-only acceptance created a Desk conversation binding")
            close_desk()

            stage = "restart_cache"
            before = len(calls)
            desk = Desk(binary, home, state)
            require(desk.recall(PHRASE)["results"] == hits, "Restart cache results differ")
            require(len(calls) == before and not desk.runtimes, "Cache restart invoked native Codex")
            report["steps"].append({"step": stage, "same_results": True, "native_calls": 0})
            report["status"] = "PASS"
        except Exception as error:
            report.update(status="FAIL", failed_stage=stage, error_type=type(error).__name__,
                          error=str(error), traceback=traceback.format_exc())
        finally:
            try:
                close_desk()
            except Exception as error:
                report.update(status="FAIL", cleanup_error=str(error))

    report["settings_unchanged"] = all(
        (path.read_bytes() if path.exists() else None) == before for path, before in settings.items())
    report["rollouts_unchanged"] = all(path.read_bytes() == before for path, before in protected.items())
    report["rollout_count_unchanged"] = set(home.rglob("rollout-*.jsonl")) == set(protected)
    report["owned_subprocesses"] = [{"pid": process.pid, "returncode": process.poll()}
                                   for process in processes]
    report["owned_subprocesses_reaped"] = all(process.poll() is not None for process in processes)
    report["owned_readers_reaped"] = all(not reader.is_alive() for reader in readers)
    report["method_counts"] = dict(Counter(entry["method"] for entry in calls))
    report["send_counts"] = dict(Counter(sends))
    report["blocked_methods"] = blocked
    report["calls"] = calls
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    if blocked or not all(report[key] for key in ("settings_unchanged", "rollouts_unchanged",
            "rollout_count_unchanged", "owned_subprocesses_reaped", "owned_readers_reaped")):
        report["status"] = "FAIL"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True, help="Absolute native Codex executable path")
    parser.add_argument("--work-dir", required=True, help="Absolute scratch directory; synthetic data is retained")
    parser.add_argument("--receipt", help="Write the detailed JSON receipt to this path")
    args = parser.parse_args()
    try:
        report = run_check(args)
    except Exception as error:
        report = {"status": "FAIL", "failed_stage": "fixture_setup", "error": str(error),
                  "error_type": type(error).__name__, "traceback": traceback.format_exc()}
    if args.receipt:
        receipt = Path(args.receipt).expanduser()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if report["status"] == "PASS":
        print(f"PASS: {report['native_version']}; synthetic vscode+cli indexed; exec hidden; "
              "2 exact-original reads; cache restart uses 0 native calls")
    else:
        print(f"FAIL: {report.get('failed_stage', 'cleanup')}: "
              f"{report.get('error', report.get('cleanup_error', 'integrity/shutdown check failed'))}")
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
