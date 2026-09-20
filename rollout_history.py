"""Project-authorized public history from a single local session journal.

Only completed UserMessage/AgentMessage items are selected. No raw response
items, tools, reasoning, compaction text or session instructions leave the host.
"""
from datetime import datetime
import json
from bridge import BridgeError


def read_public(path,thread):
    if path.is_symlink():raise BridgeError('Session symlinks are not accepted')
    turns={};identity=False;skip=set()
    with path.open() as stream:
        for line in stream:
            try:record=json.loads(line)
            except ValueError:continue
            p=record.get('payload',{})
            if record.get('type')=='session_meta':
                if p.get('id')!=thread:raise BridgeError('Session belongs to another task')
                identity=True
            if record.get('type')!='event_msg' or p.get('type')!='item_completed' or p.get('thread_id')!=thread:continue
            tid=p.get('turn_id');item=p.get('item',{})
            if not isinstance(tid,str):continue
            if item.get('type')=='FunctionCallOutput' and item.get('namespace')=='codex_app' and item.get('name')=='send_message_to_thread':
                skip.add(tid);continue
            kind=item.get('type')
            if kind not in ('UserMessage','AgentMessage'):continue
            if kind=='AgentMessage' and item.get('phase') not in ('commentary','final_answer'):continue
            text='\n'.join(c['text'] for c in item.get('content',[]) if c.get('type') in ('text','Text') and isinstance(c.get('text'),str))
            if not text.strip():continue
            if kind=='UserMessage' and text.lstrip().startswith(('<heartbeat>','<codex_internal_context','<environment_context>','<recommended_plugins>')):
                skip.add(tid);continue
            try:created=int(datetime.fromisoformat(record['timestamp'].replace('Z','+00:00')).timestamp())
            except (KeyError,TypeError,ValueError):raise BridgeError('Missing public message timestamp')
            turn=turns.setdefault(tid,{'id':tid,'startedAt':created,'items':[]})
            entry={'id':item['id'],'type':'userMessage' if kind=='UserMessage' else 'agentMessage'}
            if kind=='UserMessage':entry['content']=[{'type':'text','text':text}]
            else:entry.update(text=text,phase=item['phase'])
            if not any(old['id']==entry['id'] for old in turn['items']):turn['items'].append(entry)
    if not identity:raise BridgeError('Missing session identity')
    return {'thread':{'id':thread},'turns':[t for k,t in turns.items() if k not in skip],'page':{'hasMore':False,'nextCursor':None}}
