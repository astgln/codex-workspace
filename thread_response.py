"""Select a public response only from the exact marked Codex turn.

Input comes from the authorized read_thread tool. Never read Codex's databases
or export a thread's old turns as a substitute for an absent response.
"""
from runtime_support import BridgeError


def prompt_prefix(marker):
    return f'Workspace request: {marker}\n'


def correlate(read, thread, marker, baseline):
    if not isinstance(read, dict) or read.get('thread', {}).get('id') != thread:
        raise BridgeError('Thread read does not match the approved target')
    matches=[]
    for turn in read.get('turns', []):
        if not isinstance(turn, dict) or turn.get('id') == baseline:
            continue
        for item in turn.get('items', []):
            if item.get('type') != 'userMessage':
                continue
            text='\n'.join(part['text'] for part in item.get('content', [])
                           if part.get('type') == 'text' and isinstance(part.get('text'), str))
            if text.startswith(prompt_prefix(marker)):
                matches.append(turn)
                break
    if len(matches)>1:
        raise BridgeError('Marker occurs in multiple turns; manual reconciliation required')
    if not matches:
        return None
    turn=matches[0]
    if not isinstance(turn.get('id'),str) or not turn['id']:
        raise BridgeError('Marked turn has no stable ID')
    status=turn.get('status')
    if status not in ('completed','failed','interrupted','inProgress','running'):
        return None
    events=[]
    for item in turn.get('items', []):
        if item.get('type')=='agentMessage' and item.get('phase')=='final_answer':
            text=item.get('text')
            if isinstance(text,str) and text.strip():
                events.append({'type':'agent_message','text':text})
    if status=='completed' and not events:
        # Metadata alone is insufficient evidence of a response. Retry the read,
        # not dispatch, and do not export another turn's text.
        return None
    if status in ('failed','interrupted'):
        events.append({'type':'error','message':'Выполнение запроса остановлено. Требуется проверка в Codex.'})
    return {'thread':thread,'marker':marker,'turn_id':turn['id'],
            'status':'completed' if status=='completed' else 'failed' if status in ('failed','interrupted') else 'running',
            'events':events}
