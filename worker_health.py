"""Content-free summary of the last completed collector pass."""
from runtime_support import BridgeError

REASONS = ('desktop_writer_lock', 'task_settings_unavailable')


def summary(result):
    waiting = {reason: 0 for reason in REASONS}
    for item in result.get('requests', []):
        if item.get('reason') in waiting:
            waiting[item['reason']] += 1
    unresolved = len(result.get('ids', []))
    if result.get('status') == 'needs_reconciliation' and 'id' in result:
        unresolved += 1
    return {'status': result['status'], 'waiting': waiting, 'unresolved': unresolved}


def publish(api, result):
    try:
        api.call('/v2/worker/status', summary(result))
    except (BridgeError, OSError, ValueError, KeyError):
        # Diagnostics must never alter dispatch state or cause a second execution.
        return False
    return True
