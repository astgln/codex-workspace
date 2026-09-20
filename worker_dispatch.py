"""Coordinate permission preflight, durable dispatch intent and recovery."""
import json
import subprocess
from bridge import BridgeError
from cli_session import snapshot, command
from worker_recovery import collect, request_text
from worker_execution import execute


def dispatch_one(queue, home, executable, catalog, run=subprocess.run, *, api):
    # Recover first. An interrupted dispatch is never submitted a second time.
    for row in queue.db.execute("SELECT * FROM requests WHERE status IN ('dispatching','dispatched')").fetchall():
        collect(queue,home,row)
    allowed = {item['id']:item for item in catalog['threads'] if not item.get('read_only',False)}
    waiting=[]
    for item in queue.pending()['messages']:
        if item['local_status'] != 'pending' or item['thread'] not in allowed:
            continue
        unresolved = queue.db.execute("SELECT 1 FROM requests WHERE status IN ('dispatching','dispatched') AND json_extract(payload,'$.thread')=?",(item['thread'],)).fetchone()
        if unresolved:
            continue
        try:
            state = snapshot(home,item['thread'])
            if state['status'] != 'ready':
                waiting.append({'id':item['id'],'reason':'desktop_writer_lock'})
                continue
            args = command(executable,state)
        except (BridgeError,OSError,ValueError,KeyError):
            # One unsupported task must not stop unrelated approved requests.
            # No dispatch intent is created until settings can be preserved.
            waiting.append({'id':item['id'],'reason':'task_settings_unavailable'})
            continue
        request = queue.begin(item['id'],item['thread'],state['baseline'],api=api)
        prompt = request_text(request)
        with queue.db:
            row=queue.db.execute('SELECT dispatch FROM requests WHERE id=?',(item['id'],)).fetchone()
            dispatch=json.loads(row['dispatch'])
            dispatch.update(transport='cli',prompt=prompt,settings=state['settings'])
            queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
        result = execute(queue.state, item['id'], args, prompt, state['settings']['cwd'], run)
        with queue.db:
            dispatch['exit_code']=result.returncode
            queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
        row=queue.db.execute('SELECT * FROM requests WHERE id=?',(item['id'],)).fetchone()
        matched=collect(queue,home,row)
        return {'status':'completed' if matched else 'needs_reconciliation','id':item['id']}
    unresolved = [row['id'] for row in queue.db.execute(
        "SELECT id FROM requests WHERE status IN ('dispatching','dispatched')")]
    if unresolved:
        return {'status':'needs_reconciliation','ids':unresolved}
    if waiting:
        return {'status':'waiting_for_tasks','requests':waiting}
    return {'status':'idle'}


