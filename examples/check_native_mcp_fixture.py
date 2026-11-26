#!/usr/bin/env python3
"""Exercise the synthetic stdio fixture without a Codex or model process."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "desk_acceptance_report", "arguments": {"case": "success"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "desk_acceptance_report", "arguments": {"case": "error"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "ping"},
    ]
    result = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name("native_mcp_fixture.py"))],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True, text=True, timeout=5, check=True,
    )
    assert result.stderr == "", result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4, 5]
    assert all(reply["jsonrpc"] == "2.0" for reply in replies)
    assert replies[0]["result"] == {
        "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
        "serverInfo": {"name": "desk-acceptance", "version": "1"},
    }
    tool, = replies[1]["result"]["tools"]
    assert tool["name"] == "desk_acceptance_report"
    assert tool["annotations"] == {"readOnlyHint": True, "destructiveHint": False}
    assert tool["inputSchema"]["properties"]["case"]["enum"] == ["success", "error"]
    assert replies[2]["result"] == {
        "content": [{"type": "text", "text": "Synthetic local acceptance: three checks passed"}],
        "structuredContent": {"fixture": "local-only", "passed": 3},
    }
    assert replies[3]["result"] == {
        "content": [{"type": "text", "text": "Deliberate acceptance error: fixture unavailable"}],
        "isError": True,
    }
    assert replies[4]["result"] == {}
    print("PASS: 2 tool-call cases; initialize/list/ping verified")


if __name__ == "__main__":
    main()
