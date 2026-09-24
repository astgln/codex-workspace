"""Endpoint-only notification previews, encrypted before reaching the relay."""
import time
from codex_workspace.domain.redaction import public_text


def publish(channel,thread,record,title,text,created=None):
    created=int(time.time()) if created is None else created
    if type(created) is not int or created<int(time.time())-60:return
    title=' '.join(public_text(title).split())[:70]
    text=' '.join(public_text(text).split())[:220]
    channel.snapshot(thread,'push',record,{'thread':thread,'title':title or 'Codex Workspace',
                                         'body':text or 'Готов новый ответ','created':created})
