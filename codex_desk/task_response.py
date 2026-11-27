"""Select one supplied assistant response from an exact captured native parent turn."""

def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError('Use the captured native thread and turn IDs')
    return value


def select_task_response(thread, thread_id, turn_id):
    identifier(thread_id)
    identifier(turn_id)
    if not isinstance(thread, dict) or thread.get('id') != thread_id:
        raise ValueError('Native original does not match the captured parent thread')
    turns = thread.get('turns')
    if not isinstance(turns, list):
        raise ValueError('Native original did not supply its turns')
    result = {'thread_id': thread_id, 'turn_id': turn_id,
              'available': False, 'turn_status': None, 'turn_error': None,
              'source': 'native history read'}
    matching = [turn for turn in turns if isinstance(turn, dict) and turn.get('id') == turn_id]
    if not matching:
        return {**result, 'status': 'turn_unavailable', 'reason': 'turn_unavailable'}
    if len(matching) != 1:
        raise ValueError('Native original supplied an ambiguous captured turn')
    turn = matching[0]
    result['turn_status'] = turn.get('status') if isinstance(turn.get('status'), str) else None
    result['turn_error'] = turn.get('error')
    items = turn.get('items')
    if not isinstance(items, list):
        return {**result, 'status': 'response_unavailable', 'reason': 'response_unavailable'}
    messages = [item for item in items if isinstance(item, dict)
                and item.get('type') == 'agentMessage'
                and isinstance(item.get('id'), str) and item['id'].strip() and len(item['id']) <= 200
                and isinstance(item.get('text'), str) and item['text'].strip()]
    if not messages:
        return {**result, 'status': 'response_unavailable', 'reason': 'response_unavailable'}
    final = [item for item in messages if item.get('phase') == 'final_answer']
    chosen = (final or messages)[-1]
    if sum(item.get('id') == chosen['id'] for item in items if isinstance(item, dict)) != 1:
        raise ValueError('Native original supplied an ambiguous response item')
    phase = chosen.get('phase') if isinstance(chosen.get('phase'), str) else None
    labels = {'final_answer': 'Final answer', 'commentary': 'Commentary', 'partial_answer': 'Partial answer'}
    return {**result, 'status': 'available', 'available': True, 'reason': None,
            'item_id': chosen['id'], 'phase': phase,
            'selection': 'final_answer' if final else 'last_assistant_message',
            'label': labels.get(phase, 'Last assistant message'), 'source': 'native history read'}
