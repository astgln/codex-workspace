"""Consistent privacy headers and bounded anonymous login work."""
import math
import time

class LoginBudget:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.buckets = {}

    def take(self, path):
        capacity = {'auth/device/challenge':60, 'auth/device/session':30, 'auth/pairing/offer':30, 'auth/pairing/read':120}.get(path)
        if capacity is None:
            return 0
        now = self.clock()
        tokens, previous = self.buckets.get(path, (capacity, now))
        tokens = min(capacity, tokens + max(0, now - previous) * capacity / 60)
        if tokens < 1:
            self.buckets[path] = (tokens, now)
            return max(1, math.ceil((1 - tokens) * 60 / capacity))
        self.buckets[path] = (tokens - 1, now)
        return 0


def secure_headers(response, path):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=(), usb=()'
    if path.startswith(('/auth/', '/web/', '/v2/')) or path == '/health':
        response.headers['Cache-Control'] = 'no-store'
    return response
