"""Read completed public messages, including those inside an active turn.

Never export tool output, reasoning, system instructions or partial JSON lines.
Byte offsets allow a history-only process to follow growing journals cheaply.
"""
from datetime import datetime
import json
from bridge import BridgeError
from cloud.quota import from_record


def read_public(path, thread, start_offset=0):
    if path.is_symlink():
        raise BridgeError('Session symlinks are not accepted')
    turns = {}
    quota = None
    with path.open('rb') as stream:
        first = stream.readline()
        try:
            meta = json.loads(first)
        except ValueError:
            raise BridgeError('Missing session identity') from None
        if meta.get('type') != 'session_meta' or meta.get('payload', {}).get('id') != thread:
            raise BridgeError('Session belongs to another task')
        if start_offset < 0 or start_offset > path.stat().st_size:
            raise BridgeError('Invalid history offset')
        stream.seek(start_offset or len(first))
        committed = stream.tell()
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.endswith(b'\n'):
                # The writer may still be appending this record. Retry next pass.
                break
            try:
                record = json.loads(line)
            except ValueError:
                raise BridgeError('Invalid complete journal record') from None
            committed = stream.tell()
            sample = from_record(record)
            if sample and (quota is None or sample['observed_at'] >= quota['observed_at']):
                quota = sample
            p = record.get('payload', {})
            if record.get('type') != 'event_msg' or p.get('type') != 'item_completed' or p.get('thread_id') != thread:
                continue
            tid, item = p.get('turn_id'), p.get('item', {})
            kind = item.get('type')
            if not isinstance(tid, str) or kind not in ('UserMessage', 'AgentMessage'):
                continue
            if kind == 'AgentMessage' and item.get('phase') not in ('commentary', 'final_answer'):
                continue
            text = '\n'.join(c['text'] for c in item.get('content', [])
                             if c.get('type') in ('text', 'Text') and isinstance(c.get('text'), str))
            if not text.strip():
                continue
            if kind == 'UserMessage' and text.lstrip().startswith(('<heartbeat>', '<codex_internal_context', '<environment_context>', '<recommended_plugins>')):
                continue
            try:
                created = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')).timestamp()
            except (KeyError, TypeError, ValueError):
                raise BridgeError('Missing public message timestamp') from None
            turn = turns.setdefault(tid, {'id': tid, 'startedAt': created, 'items': []})
            entry = {'id': item['id'], 'type': 'userMessage' if kind == 'UserMessage' else 'agentMessage',
                     'createdAt': created, 'position': f'{int(created * 1000):016d}:{offset:020d}'}
            if kind == 'UserMessage':
                entry['content'] = [{'type': 'text', 'text': text}]
            else:
                entry.update(text=text, phase=item['phase'])
            turn['items'].append(entry)
    return {'thread': {'id': thread}, 'turns': list(turns.values()),
            'weekly_quota': quota, 'source_offset': committed, 'page': {'hasMore': False, 'nextCursor': None}}
