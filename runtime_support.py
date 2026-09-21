"""Shared transport primitives; no Telegram or legacy queue dependencies."""
import contextlib
import fcntl
import urllib.request


class BridgeError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@contextlib.contextmanager
def exclusive(state):
    with (state / 'transport.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BridgeError('Другой процесс уже получает сообщения.') from None
        yield


