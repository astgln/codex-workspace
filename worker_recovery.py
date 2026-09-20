"""Correlate persisted replies; never resubmit an uncertain dispatch."""
import json
from rollout_response import locate, recover_cli


def collect(queue, home, row):
    dispatch = json.loads(row['dispatch'])
    if dispatch.get('transport') not in ('cli','shared','shared_probe'):
        return False
    reply = recover_cli(locate(home/'sessions',dispatch['thread']), dispatch['thread'],
                        dispatch['prompt'], dispatch['baseline'])
    if reply is None:
        return False
    if row['status'] == 'dispatching':
        queue.sent(row['id'],dispatch['marker'])
    queue.publish(row['id'],{**reply,'marker':dispatch['marker']})
    return True


def request_text(request):
    prompt=request['text']
    if request['files']:
        prompt += '\n\nВложения:\n' + '\n'.join(
            json.dumps({'name': f['name'], 'path': f['path']}, ensure_ascii=False)
            for f in request['files'])
    return prompt


