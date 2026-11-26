#!/usr/bin/env python3
"""Find a literal phrase in a saved native thread/read result; emit original IDs."""
import argparse
import json
import unicodedata


def fold(text):
    return unicodedata.normalize("NFKC", text).casefold()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="JSON-RPC result object containing thread and its turns/items")
    parser.add_argument("phrase", help="Literal substring, normalized with NFKC and casefold")
    args = parser.parse_args()
    with open(args.snapshot, encoding="utf-8") as file:
        thread = json.load(file)["thread"]
    needle = fold(args.phrase)

    for turn in thread["turns"]:
        for item in turn["items"]:
            if item.get("type") == "agentMessage":
                text = item.get("text") or ""
            elif item.get("type") == "commandExecution":
                text = item.get("aggregatedOutput") or ""
            else:
                continue
            if needle and needle in fold(text):
                print(json.dumps({
                    "threadId": thread["id"],
                    "turnId": turn["id"],
                    "itemId": item["id"],
                    "preview": text[:200],
                }, ensure_ascii=False))


if __name__ == "__main__":
    main()
