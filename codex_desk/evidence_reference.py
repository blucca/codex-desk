"""A readable, exact-source quote stored inside existing local draft text.

Offsets are Unicode code points, independent of browser UTF-16 indexing.
The caller supplies the agreed history-reader item-text projection on capture
and fresh-source resolution; the module does not maintain another renderer.
"""
import json
import re
import unicodedata


VERSION = 1
OFFSET_UNIT = 'unicode_codepoints'
PROJECTION = 'history-reader-text/v1'
MAX_DRAFT_CHARS = 200_000
MAX_QUOTE_CHARS = 8_000
MAX_SAFE_OFFSET = 2**53 - 1
OPEN = '<!-- codex-desk-evidence:v1 '
CLOSE = '<!-- /codex-desk-evidence:v1 -->'
SOURCE_KINDS = frozenset(('userMessage', 'agentMessage', 'plan', 'commandExecution',
    'fileChange', 'mcpToolCall', 'dynamicToolCall', 'collabAgentToolCall', 'subAgentActivity'))
FIELDS = frozenset(('version', 'native_home', 'thread_id', 'turn_id', 'item_id',
    'source_kind', 'phase', 'status', 'turn_status', 'projection', 'offset_unit',
    'quote_start', 'quote_end', 'quote', 'title', 'cwd'))
_BLOCK = re.compile(r'^' + re.escape(OPEN) + r'(?P<metadata>[^\r\n]*) -->\r?\n'
                    r'.*?^' + re.escape(CLOSE) + r'(?=\r?\n|$)', re.M | re.S)
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')


def _scalar_text(value, limit, field, *, empty=False):
    if (not isinstance(value, str) or len(value) > limit or
            (not empty and not value) or any(unicodedata.category(c) == 'Cs' for c in value)):
        raise ValueError('Use readable ' + field)
    return value


def _identifier(value, field):
    _scalar_text(value, 200, field)
    if any(c.isspace() or unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('Use the exact native ' + field)
    return value


def _home(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('Use the captured opaque native home namespace')
    return value


def _label(value, limit):
    if not isinstance(value, str):
        return ''
    readable = ''.join(' ' if c.isspace() else c
        for c in value if not unicodedata.category(c).startswith('C') or c.isspace())
    return ' '.join(readable.split())[:limit].strip()


def _reported(value):
    if not isinstance(value, str) or not value:
        return None
    _scalar_text(value, 120, 'native phase/status')
    if any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('Use the reported native phase/status')
    return value


def _slice_quote(text, start, end):
    if (type(start) is not int or type(end) is not int or
            not 0 <= start < end <= min(MAX_SAFE_OFFSET, len(text))):
        raise ValueError('Choose a nonempty original Unicode code-point quote span')
    if end - start > MAX_QUOTE_CHARS:
        raise ValueError(f'Choose at most {MAX_QUOTE_CHARS:,} original quote characters')
    return _scalar_text(text[start:end], MAX_QUOTE_CHARS, 'original quote')


def _item(thread, thread_id, turn_id, item_id):
    if not isinstance(thread, dict) or thread.get('id') != thread_id:
        raise ValueError('The original does not match the captured native thread')
    turns = thread.get('turns')
    if not isinstance(turns, list):
        raise ValueError('The original did not supply native turns')
    found = [turn for turn in turns if isinstance(turn, dict) and turn.get('id') == turn_id]
    if len(found) != 1:
        raise ValueError('The captured original turn is unavailable or ambiguous')
    turn = found[0]
    items = turn.get('items')
    if not isinstance(items, list):
        raise ValueError('The original turn did not supply native items')
    found = [item for item in items if isinstance(item, dict) and item.get('id') == item_id]
    if len(found) != 1:
        raise ValueError('The captured original item is unavailable or ambiguous')
    return turn, found[0]


def _validate(reference):
    if not isinstance(reference, dict) or set(reference) != FIELDS:
        raise ValueError('Use a complete Codex Desk evidence reference')
    if type(reference['version']) is not int or reference['version'] != VERSION:
        raise ValueError('Use evidence reference version 1')
    _home(reference['native_home'])
    for field in ('thread_id', 'turn_id', 'item_id'):
        _identifier(reference[field], field)
    if not isinstance(reference['source_kind'], str) or reference['source_kind'] not in SOURCE_KINDS:
        raise ValueError('Use a readable native source kind')
    for field in ('phase', 'status', 'turn_status'):
        if reference[field] is not None and _reported(reference[field]) != reference[field]:
            raise ValueError('Use the reported native phase/status')
    for field, limit in (('title', 240), ('cwd', 4096)):
        _scalar_text(reference[field], limit, field, empty=True)
        if _label(reference[field], limit) != reference[field]:
            raise ValueError('Use stripped readable source labels')
    quote = _scalar_text(reference['quote'], MAX_QUOTE_CHARS, 'original quote')
    if reference['projection'] != PROJECTION or reference['offset_unit'] != OFFSET_UNIT:
        raise ValueError('Use the original reader projection and Unicode code-point offsets')
    start, end = reference['quote_start'], reference['quote_end']
    if (type(start) is not int or type(end) is not int or
            not 0 <= start < end <= MAX_SAFE_OFFSET or end - start != len(quote)):
        raise ValueError('Use the exact original Unicode code-point quote span')
    return reference


def capture_reference(thread, *, native_home, thread_id, turn_id, item_id,
                      quote_start, quote_end, text_for_item, expected_quote=None):
    """Capture one native original's exact item/quote without changing it."""
    _home(native_home)
    for field, value in (('thread_id', thread_id), ('turn_id', turn_id), ('item_id', item_id)):
        _identifier(value, field)
    turn, item = _item(thread, thread_id, turn_id, item_id)
    kind = item.get('type')
    if not isinstance(kind, str) or kind not in SOURCE_KINDS:
        raise ValueError('Use a readable native source kind')
    text = text_for_item(item)
    if not isinstance(text, str):
        raise ValueError('The original projection did not return text')
    quote = _slice_quote(text, quote_start, quote_end)
    if expected_quote is not None and (not isinstance(expected_quote, str) or quote != expected_quote):
        raise ValueError('The selected quote does not match this exact original span')
    return _validate({'version': VERSION, 'native_home': native_home,
        'thread_id': thread_id, 'turn_id': turn_id, 'item_id': item_id,
        'source_kind': kind, 'phase': _reported(item.get('phase')),
        'status': _reported(item.get('status')), 'turn_status': _reported(turn.get('status')),
        'projection': PROJECTION, 'offset_unit': OFFSET_UNIT,
        'quote_start': quote_start, 'quote_end': quote_end,
        'quote': quote, 'title': _label(thread.get('name') or thread.get('title') or thread.get('preview'), 240),
        'cwd': _label(thread.get('cwd'), 4096)})


def _json(value):
    # ASCII escapes preserve exact Unicode/CRLF in the metadata while literal
    # comment delimiters cannot be introduced through native source text.
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def format_evidence_block(reference):
    """One canonical markdown block: versioned metadata and readable evidence."""
    _validate(reference)
    encoded = _json(reference).replace('<', '\\u003c').replace('>', '\\u003e')
    report = lambda value: value if value is not None else 'unreported'
    quote = reference['quote'].replace('\r\n', '\n').replace('\r', '\n')
    lines = [OPEN + encoded + ' -->',
        'Codex source: ' + (reference['title'] or 'Original Codex conversation'),
        'Native home: ' + reference['native_home'],
        'Thread: ' + reference['thread_id'], 'Turn: ' + reference['turn_id'],
        'Item: ' + reference['item_id'], 'Kind: ' + reference['source_kind'],
        'Phase: ' + report(reference['phase']), 'Item status: ' + report(reference['status']),
        'Turn status: ' + report(reference['turn_status']),
        'Project folder: ' + (reference['cwd'] or 'unreported'),
        'Projection: ' + reference['projection'],
        'Quote span: ' + str(reference['quote_start']) + '..' + str(reference['quote_end']) +
            ' (' + reference['offset_unit'] + ')',
        'Original excerpt:', *('> ' + line for line in quote.split('\n')), CLOSE]
    block = '\n'.join(lines)
    if len(block) > MAX_DRAFT_CHARS:
        raise ValueError('The evidence block exceeds the local draft text limit')
    return block


def make_evidence_block(thread, **capture):
    return format_evidence_block(capture_reference(thread, **capture))


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Repeated metadata field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Invalid JSON constant')


def _fenced_ranges(text):
    ranges, opened, fence, offset = [], None, None, 0
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line.rstrip('\r\n'))
        if match:
            delimiter, tail = match.groups()
            if fence is None:
                if delimiter[0] != '`' or '`' not in tail:
                    fence, opened = delimiter, offset
            elif delimiter[0] == fence[0] and len(delimiter) >= len(fence) and not tail.strip():
                ranges.append((opened, offset + len(line)))
                fence, opened = None, None
        offset += len(line)
    if fence is not None:
        ranges.append((opened, len(text)))
    return ranges


def parse_evidence_blocks(draft_text):
    """Yield only unedited well-formed own blocks; raw draft text stays intact.

    Each result has the reference plus Python text start/end offsets so an
    owner can render its exact existing block. Fenced examples are plain text.
    """
    if not isinstance(draft_text, str) or len(draft_text) > MAX_DRAFT_CHARS:
        return []
    found, fences = [], _fenced_ranges(draft_text)
    for match in _BLOCK.finditer(draft_text):
        if any(first <= match.start() < last for first, last in fences):
            continue
        try:
            metadata = json.loads(match['metadata'], object_pairs_hook=_strict_object,
                                  parse_constant=_invalid_constant)
            if not isinstance(metadata, dict) or set(metadata) != FIELDS:
                continue
            reference = metadata
            _validate(reference)
            if match.group().replace('\r\n', '\n') != format_evidence_block(reference):
                continue
            found.append({'reference': reference, 'start': match.start(), 'end': match.end()})
        except (ValueError, TypeError, KeyError, RecursionError):
            continue
    return found


def append_evidence_block(draft_text, block):
    """Append one reviewed own block using the existing 200K draft limit."""
    if not isinstance(draft_text, str) or not isinstance(block, str):
        raise ValueError('Use local draft and evidence text')
    parsed = parse_evidence_blocks(block)
    if len(parsed) != 1 or parsed[0]['start'] != 0 or parsed[0]['end'] != len(block):
        raise ValueError('Review a complete unchanged evidence block before appending')
    result = draft_text + ('\n\n' if draft_text else '') + block
    if len(result) > MAX_DRAFT_CHARS:
        raise ValueError('The appended evidence exceeds the local draft text limit')
    return result


def reference_target(reference, native_home):
    """Resolve the original namespace before a caller performs any native read."""
    _validate(reference)
    _home(native_home)
    if reference['native_home'] != native_home:
        raise ValueError('This original belongs to a different native home')
    return {key: reference[key] for key in ('thread_id', 'turn_id', 'item_id')}


def resolve_reference(reference, native_home, thread, *, text_for_item):
    """Compare the same item's exact span in a supplied fresh original snapshot."""
    _validate(reference)
    _home(native_home)
    result = {'available': False, 'thread_id': reference['thread_id'],
        'turn_id': reference['turn_id'], 'item_id': reference['item_id']}
    if reference['native_home'] != native_home:
        return {**result, 'status': 'home_mismatch'}
    try:
        turn, item = _item(thread, reference['thread_id'], reference['turn_id'], reference['item_id'])
    except ValueError:
        return {**result, 'status': 'source_unavailable'}
    if item.get('type') != reference['source_kind']:
        return {**result, 'status': 'source_kind_changed'}
    try:
        text = text_for_item(item)
        if not isinstance(text, str):
            raise ValueError('The original projection did not return text')
        quote = _slice_quote(text, reference['quote_start'], reference['quote_end'])
    except (ValueError, TypeError, KeyError):
        return {**result, 'status': 'quote_unavailable'}
    if quote != reference['quote']:
        return {**result, 'status': 'quote_changed'}
    current = {'phase': _reported(item.get('phase')), 'status': _reported(item.get('status')),
        'turn_status': _reported(turn.get('status'))}
    return {**result, 'available': True, 'status': 'available', 'current': current,
        'state_changed': any(current[key] != reference[key] for key in current),
        'quote_start': reference['quote_start'], 'quote_end': reference['quote_end'],
        'offset_unit': OFFSET_UNIT, 'projection': PROJECTION}
