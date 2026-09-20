"""Recover one marked public reply when the app read tool omits turn items.

Only the selected thread's session journal is read. No reasoning, arbitrary tool
outputs, compaction summaries or historical replies are returned. The caller
must first verify the selected turn and its completion with Codex app tools.
"""
import json
import re
from pathlib import Path
from bridge import BridgeError

UUID=re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')


def recover(path,thread,marker,source_thread,turn_id):
    if not all(UUID.fullmatch(v) for v in (thread,source_thread,turn_id)):
        raise BridgeError('Invalid task identity')
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise BridgeError('Invalid session file')
    matched=set(); finals={}; completed=set(); identity=False
    envelope=f'<codex_delegation>\n  <source_thread_id>{source_thread}</source_thread_id>\n  <input>Workspace request: {marker}\n'
    with path.open() as stream:
        for line in stream:
            try:record=json.loads(line)
            except ValueError:continue  # A writer may still be appending a line.
            payload=record.get('payload',{})
            if record.get('type')=='session_meta':
                if payload.get('id')!=thread:raise BridgeError('Session belongs to another task')
                identity=True
            if record.get('type')!='event_msg':continue
            turn=payload.get('turn_id')
            if payload.get('type')=='task_complete':completed.add(turn)
            if payload.get('type')!='item_completed' or payload.get('thread_id')!=thread:continue
            item=payload.get('item',{})
            if (item.get('type')=='FunctionCallOutput' and item.get('namespace')=='codex_app'
                    and item.get('name')=='send_message_to_thread'):
                value=item.get('output')
                if isinstance(value,str) and value.startswith(envelope):matched.add(turn)
            if turn==turn_id and item.get('type')=='AgentMessage' and item.get('phase')=='final_answer':
                texts=[c['text'] for c in item.get('content',[]) if c.get('type')=='Text' and isinstance(c.get('text'),str)]
                if texts:finals[item['id']]='\n'.join(texts)
    if not identity:raise BridgeError('Missing session identity')
    if len(matched)>1:raise BridgeError('Duplicate delivery marker; manual reconciliation required')
    if matched and matched!={turn_id}:raise BridgeError('Marker belongs to a different turn')
    if not matched or turn_id not in completed or not finals:return None
    return {'thread':thread,'marker':marker,'turn_id':turn_id,'status':'completed',
            'events':[{'type':'agent_message','text':text} for text in finals.values()]}


def locate(root,thread):
    if not UUID.fullmatch(thread):raise BridgeError('Invalid task identity')
    matches=list(Path(root).glob(f'*/*/*/rollout-*-{thread}.jsonl'))
    if len(matches)!=1:raise BridgeError('Session file missing or ambiguous')
    return matches[0]
