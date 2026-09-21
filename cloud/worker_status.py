"""Strictly bounded collector diagnostics, without task IDs or content."""
STATUSES = ('idle', 'completed', 'waiting_for_tasks', 'needs_reconciliation', 'stopping')
REASONS = {'desktop_writer_lock', 'task_settings_unavailable'}


def save(state, body, now):
    if not isinstance(body, dict) or set(body) != {'status', 'waiting', 'unresolved'}:
        raise ValueError('Invalid worker status')
    waiting = body['waiting']
    if (body['status'] not in STATUSES or not isinstance(waiting, dict) or
            set(waiting) != REASONS or any(type(n) is not int or not 0 <= n <= 1000
            for n in [*waiting.values(), body['unresolved']])):
        raise ValueError('Invalid worker status')
    state['worker_status'] = {**body, 'observed_at': now}
    return {'ok': True}
