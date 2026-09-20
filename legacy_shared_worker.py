"""Retired shared App Server experiment, excluded from the CLI service.

Retained only for historical tests. No installed service imports this module.
"""
import json
from bridge import BridgeError
from cli_session import snapshot
from worker_recovery import collect, request_text


async def dispatch_shared(queue, home, socket, catalog, client_factory=None, *, api):
    from shared_rpc import SharedRPC
    client_factory=client_factory or SharedRPC
    for row in queue.db.execute("SELECT * FROM requests WHERE status IN ('dispatching','dispatched')").fetchall():
        collect(queue,home,row)
    allowed={t['id'] for t in catalog['threads'] if not t.get('read_only',False)}
    pending=[m for m in queue.pending()['messages'] if m['local_status']=='pending' and m['thread'] in allowed]
    waiting=[]
    if pending:
        async with client_factory(socket) as client:
            for item in pending:
                unresolved=queue.db.execute("SELECT 1 FROM requests WHERE status IN ('dispatching','dispatched') AND json_extract(payload,'$.thread')=?",(item['thread'],)).fetchone()
                if unresolved:
                    continue
                metadata=await client.call('thread/read',{'threadId':item['thread'],'includeTurns':False})
                if metadata['thread']['status']['type'] not in ('idle','notLoaded'):
                    waiting.append({'id':item['id'],'reason':'task_active'})
                    continue
                before=snapshot(home,item['thread'],require_unowned=False)
                resumed=await client.call('thread/resume',{'threadId':item['thread'],'excludeTurns':True})
                if resumed['thread']['status']['type']!='idle':
                    waiting.append({'id':item['id'],'reason':'task_active'})
                    continue
                after=snapshot(home,item['thread'],require_unowned=False)
                if before['settings']!=after['settings']:
                    raise BridgeError('Shared resume changed task settings; dispatch stopped')
                request=queue.begin(item['id'],item['thread'],after['baseline'],api=api)
                prompt=request_text(request)
                with queue.db:
                    row=queue.db.execute('SELECT dispatch FROM requests WHERE id=?',(item['id'],)).fetchone()
                    dispatch=json.loads(row['dispatch'])
                    dispatch.update(transport='shared',prompt=prompt,settings=after['settings'])
                    queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
                started=await client.call('turn/start',{'threadId':item['thread'],'input':[{'type':'text','text':prompt}]})
                turn=started['turn']['id']
                with queue.db:
                    dispatch['turn_id']=turn
                    queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
                queue.sent(item['id'],request['marker'])
                try:
                    await client.wait_completed(item['thread'],turn)
                except TimeoutError:
                    # The accepted turn may still be running. Keep its durable ID
                    # and collect the persisted reply on later polling cycles.
                    return {'status':'awaiting_completion','id':item['id']}
                row=queue.db.execute('SELECT * FROM requests WHERE id=?',(item['id'],)).fetchone()
                matched=collect(queue,home,row)
                return {'status':'completed' if matched else 'awaiting_persisted_reply','id':item['id']}
    unresolved=[row['id'] for row in queue.db.execute("SELECT id FROM requests WHERE status IN ('dispatching','dispatched')")]
    if unresolved:
        return {'status':'needs_reconciliation','ids':unresolved}
    return {'status':'waiting_for_tasks','requests':waiting} if waiting else {'status':'idle'}


