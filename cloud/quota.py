"""Whitelist account-wide weekly quota metadata; never forward raw account data."""
import math
from datetime import datetime


def from_record(record):
    p = record.get('payload', {})
    limits = p.get('rate_limits')
    if record.get('type') != 'event_msg' or p.get('type') != 'token_count' or not isinstance(limits, dict) or limits.get('limit_id') != 'codex':
        return None
    try:
        observed = int(datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')).timestamp())
        for key in ('primary', 'secondary'):
            window = limits.get(key)
            if isinstance(window, dict) and window.get('window_minutes') == 10080:
                result = {'used_percent': window.get('used_percent'), 'resets_at': window.get('resets_at'), 'observed_at': observed}
                return result if valid(result) else None
    except (KeyError, ValueError, TypeError):
        pass
    return None


def valid(value):
    return (isinstance(value, dict) and set(value) == {'used_percent', 'resets_at', 'observed_at'}
            and type(value['used_percent']) in (int, float) and math.isfinite(value['used_percent'])
            and 0 <= value['used_percent'] <= 100 and type(value['observed_at']) is int
            and type(value['resets_at']) is int and 0 < value['observed_at'] < value['resets_at']
            and value['resets_at'] - value['observed_at'] <= 8 * 86400)
