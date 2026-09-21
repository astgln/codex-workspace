"""Correlate persisted replies; never resubmit an uncertain dispatch."""
import json
from runtime_support import BridgeError
from rollout_response import locate, recover_cli


def collect(queue, home, row, *, include_running=False):
    dispatch = json.loads(row['dispatch'])
    if dispatch.get('transport') not in ('cli','shared','shared_probe'):
        return False
    try:
        reply = recover_cli(locate(home/'sessions',dispatch['thread']), dispatch['thread'],
                            dispatch['prompt'], dispatch['baseline'], include_running=include_running)
    except (BridgeError, OSError, ValueError, KeyError):
        # A missing/unsupported journal is not proof that execution failed.
        # Preserve intent and block only this task; other tasks may proceed.
        return False
    if reply is None:
        return False
    if row['result']:
        previous = json.loads(row['result'])
        if previous['status'] == reply['status'] and previous['events'] == reply['events']:
            return reply['status'] in ('completed', 'failed')
    if row['status'] == 'dispatching':
        queue.sent(row['id'],dispatch['marker'])
    queue.publish(row['id'],{**reply,'marker':dispatch['marker']})
    return reply['status'] in ('completed', 'failed')


def request_text(request):
    prompt=request['text']
    if request['files']:
        prompt += '\n\nВложения:\n' + '\n'.join(
            json.dumps({'name': f['name'], 'path': f['path']}, ensure_ascii=False)
            for f in request['files'])
    return prompt


