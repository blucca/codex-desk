#!/usr/bin/env python3
"""Synthetic read-only stdio MCP fixture used for Codex Desk tool evidence.

The success and deliberate-error responses match the recorded acceptance fixture.
Run with Python 3; requests and responses are one JSON-RPC object per line.
"""
import json
import sys


def respond(message):
    method = message.get("method")
    params = message.get("params") or {}
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "desk-acceptance", "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [{
                "name": "desk_acceptance_report",
                "description": "Get a synthetic local acceptance report. Select case=error to test a deliberate tool failure. Read-only, no files changed.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"case": {"type": "string", "enum": ["success", "error"]}},
                    "required": ["case"],
                },
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            }],
        }
    elif method == "tools/call":
        if params.get("arguments", {}).get("case") == "error":
            result = {
                "content": [{"type": "text", "text": "Deliberate acceptance error: fixture unavailable"}],
                "isError": True,
            }
        else:
            result = {
                "content": [{"type": "text", "text": "Synthetic local acceptance: three checks passed"}],
                "structuredContent": {"fixture": "local-only", "passed": 3},
            }
    else:
        result = {}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    for line in sys.stdin:
        try:
            reply = respond(json.loads(line))
            if reply is not None:
                print(json.dumps(reply), flush=True)
        except Exception as error:
            print(str(error), file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
