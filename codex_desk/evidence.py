"""Readable native tool evidence for the editable handoff, without media payloads."""
import json
from urllib.parse import urlsplit, urlunsplit


def _inline_description(value, label='Inline media'):
    if not isinstance(value, str):
        return f'[{label}: unavailable payload]'
    if value.lower().startswith('data:'):
        header, separator, body = value.partition(',')
        mime = header[5:].split(';', 1)[0][:80] or 'unspecified MIME type'
        return f'[{label}: {mime}; inline payload {len(body) if separator else 0} characters]'
    return f'[{label}: inline payload {len(value)} characters]'


def public_uri(value, label='Media'):
    """A plain descriptor; never read a local resource or fetch a URL."""
    if not isinstance(value, str):
        return '[Unavailable URI]'
    if value.lower().startswith('data:'):
        return _inline_description(value, label)
    try:
        parsed = urlsplit(value)
        # Preserve a public address, not access tokens or URL credentials.
        host = parsed.netloc.rsplit('@', 1)[-1]
        return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    except ValueError:
        return '[Invalid URI]'


def _review_value(value):
    """Keep JSON structure, excluding application-private metadata and binary data."""
    if isinstance(value, dict):
        result = {}
        kind = value.get('type')
        for key, entry in value.items():
            if key == '_meta':
                continue
            if key == 'blob' and isinstance(entry, str):
                result[key] = _inline_description(entry, 'Resource blob')
            elif key == 'data' and kind in ('image', 'audio'):
                result[key] = _inline_description(entry, kind.capitalize())
            elif key in ('uri', 'url', 'imageUrl', 'audioUrl') and isinstance(entry, str):
                result[key] = public_uri(entry)
            else:
                result[key] = _review_value(entry)
        return result
    if isinstance(value, list):
        return [_review_value(entry) for entry in value]
    if isinstance(value, str) and value.lower().startswith('data:'):
        return _inline_description(value)
    return value


def review_json(value):
    return json.dumps(_review_value(value), ensure_ascii=False, indent=2)


def _annotations(block):
    annotations = block.get('annotations')
    if not isinstance(annotations, dict):
        return ''
    public = {}
    audience = annotations.get('audience')
    if isinstance(audience, list) and all(isinstance(v, str) and v in ('user', 'assistant') for v in audience):
        public['audience'] = audience
    priority = annotations.get('priority')
    if isinstance(priority, (int, float)) and not isinstance(priority, bool):
        public['priority'] = priority
    if isinstance(annotations.get('lastModified'), str):
        public['lastModified'] = annotations['lastModified']
    return '\nAnnotations: ' + review_json(public) if public else ''


def _text(value):
    return value if isinstance(value, str) else '[Unavailable text content]'


def content_text(block):
    """MCP content is arbitrary JSON; dynamic content has separate tagged shapes."""
    if not isinstance(block, dict):
        return '[Unsupported content block]'
    kind = block.get('type')
    if kind in ('text', 'inputText'):
        text = 'Text\n' + _text(block.get('text'))
    elif kind in ('image', 'audio'):
        label = kind.capitalize()
        mime = block.get('mimeType') if isinstance(block.get('mimeType'), str) else 'unspecified MIME type'
        data = block.get('data')
        payload = f'inline payload {len(data)} characters' if isinstance(data, str) else 'no inline payload'
        text = f'[{label}: {mime}; {payload}]'
    elif kind in ('inputImage', 'inputAudio'):
        label, key = ('Image', 'imageUrl') if kind == 'inputImage' else ('Audio', 'audioUrl')
        uri = public_uri(block.get(key), label)
        text = uri if uri.startswith(f'[{label}:') else f'[{label}: {uri}]'
    elif kind in ('resource_link', 'resourceLink'):
        lines = ['Resource link', 'URI: ' + public_uri(block.get('uri'), 'Resource')]
        for key in ('name', 'title', 'description', 'mimeType'):
            if isinstance(block.get(key), str):
                lines.append(key + ': ' + block[key])
        if isinstance(block.get('size'), (int, float)) and not isinstance(block['size'], bool):
            lines.append('size: ' + str(block['size']))
        text = '\n'.join(lines)
    elif kind == 'resource':
        resource = block.get('resource')
        if not isinstance(resource, dict):
            text = '[Unavailable embedded resource]'
        else:
            lines = ['Embedded resource', 'URI: ' + public_uri(resource.get('uri'), 'Resource')]
            if isinstance(resource.get('mimeType'), str):
                lines.append('MIME type: ' + resource['mimeType'])
            if 'text' in resource:
                lines.extend(['Text:', _text(resource['text'])])
            if 'blob' in resource:
                lines.append(_inline_description(resource['blob'], 'Resource blob'))
            text = '\n'.join(lines)
    else:
        label = kind[:80] if isinstance(kind, str) else 'unknown'
        return '[Unsupported content type: ' + label + ']'
    return text + _annotations(block)


def tool_text(item):
    dynamic = item.get('type') == 'dynamicToolCall'
    scope = item.get('namespace') if dynamic else item.get('server')
    tool = item.get('tool') if isinstance(item.get('tool'), str) else '(unnamed)'
    name = str(scope) + '.' + tool if scope else tool
    lines = [('Dynamic tool: ' if dynamic else 'MCP tool: ') + name,
             'Status: ' + str(item.get('status', 'unknown'))]
    if item.get('durationMs') is not None:
        lines.append('Duration: ' + str(item['durationMs']) + ' ms')
    if dynamic and item.get('success') is not None:
        lines.append('Success: ' + review_json(item['success']))
    error = item.get('error')
    if error is not None:
        message = error.get('message') if isinstance(error, dict) else None
        lines.append('Error: ' + (_text(message) if message is not None else '[Unavailable error message]'))
    lines.extend(['Arguments:', review_json(item.get('arguments'))])
    result = item.get('result')
    content = item.get('contentItems') if dynamic else result.get('content') if isinstance(result, dict) else None
    if content is not None:
        if isinstance(content, list):
            if not content:
                lines.append('Content: no content blocks')
            for index, block in enumerate(content, 1):
                lines.append('Content ' + str(index) + ' — ' + content_text(block))
        else:
            lines.append('[Unsupported content list]')
    if not dynamic and isinstance(result, dict) and 'structuredContent' in result:
        lines.extend(['Structured content:', review_json(result['structuredContent'])])
    return '\n'.join(lines)
