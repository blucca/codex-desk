"""Build an editable handoff from visible native task evidence."""

def visible_text(item):
    kind = item.get('type')
    if kind == 'userMessage':
        return 'User\n' + '\n'.join(c.get('text', '') for c in item.get('content', []) if c.get('type') == 'text')
    if kind == 'agentMessage':
        return 'Codex\n' + item.get('text', '')
    if kind == 'commandExecution':
        return 'Command\n' + item.get('command', '') + '\nExit: ' + str(item.get('exitCode')) + '\n' + item.get('aggregatedOutput', '')
    if kind == 'fileChange':
        return 'File changes\n' + '\n'.join(c.get('path', '') + '\n' + c.get('diff', '') for c in item.get('changes', []))
    return ''


def build_handoff(thread, max_chars=24000):
    header = ('Continue the project task using this reviewed handoff. Check the current workspace before making further changes.\n\n'
              + 'Source thread: ' + thread['id'] + '\nWorking directory: ' + thread.get('cwd', '')
              + '\nSource provider: ' + thread.get('modelProvider', '') + '\n\n'
              + 'Goal / current request:\n[Edit this to state what you want completed next.]\n\n'
              + 'Completed:\n[Review the evidence below and record the useful completed work.]\n\n'
              + 'Remaining / constraints:\n[Edit before running.]\n\nVisible task evidence:\n')
    blocks = []
    for turn in thread.get('turns', []):
        for item in turn.get('items', []):
            text = visible_text(item)
            if text:
                blocks.append(('Item ' + item['id'] + '\n' + text))
    kept, size, omitted = [], len(header), 0
    # Keep recent evidence in its original order, with an explicit cutoff.
    for block in reversed(blocks):
        available = max_chars - size - 240
        if available <= 0:
            omitted += 1
            continue
        if len(block) > available:
            block = block[:available] + '\n[This item was shortened at the handoff character limit.]'
        kept.insert(0, block)
        size += len(block) + 8
    cutoff = '\n\nEarlier visible items omitted: ' + str(omitted) + '. Character budget: ' + str(max_chars) + '.\n'
    return header + '\n\n---\n\n'.join(kept) + cutoff
