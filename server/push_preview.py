"""Bounded notification previews tied to an exact completed answer event."""
import re


def preview(text, limit=500):
    if not isinstance(text, str):
        return ''
    text = re.sub(r'\b\d{6,15}:[A-Za-z0-9_-]{30,}\b', '[token hidden]', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b', '[credential hidden]', text)
    text = re.sub(r'(?im)^(\s*(?:export\s+)?[A-Z_]*(?:TOKEN|PASSWORD|SECRET|API_KEY)[A-Z_]*\s*=).+$', r'\1[hidden]', text)
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit-1] + '…'


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS push_previews(event TEXT PRIMARY KEY,text TEXT NOT NULL)')


def record(db, event, text):
    db.execute('INSERT OR IGNORE INTO push_previews VALUES(?,?)', (event, preview(text)))


def payload(store, state, event, thread, kind):
    title = preview(state.get('catalog', {}).get(thread, {}).get('title'), 120) or 'Codex Workspace'
    text = ''
    if kind == 'approval':
        text = preview(state['items'].get(event.split(':', 1)[1], {}).get('text'))
        body = 'На одобрение: ' + text if text else 'Новый запрос на одобрение'
    else:
        db = store.connect()
        try:
            row = db.execute('SELECT text FROM push_previews WHERE event=?', (event,)).fetchone()
            if row:
                text = row[0]
        finally:
            db.close()
        if not text:
            for item in state['items'].values():
                if item.get('channel') != 'web' or item.get('thread') != thread or item.get('result_status') != 'completed':
                    continue
                key = 'answer:'+thread+':'+item['result_turn_id'] if item.get('result_turn_id') else 'reply:'+str(item['id'])
                if key == event:
                    text = next((e.get('text', '') for e in reversed(item.get('events', [])) if e.get('type') == 'agent_message'), '')
                    break
        body = preview(text) or 'Готов новый ответ'
    return {'title': title, 'body': body,
            'url': '/#approvals' if kind == 'approval' else '/#thread='+thread, 'tag': kind+':'+thread}
