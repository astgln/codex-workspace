"""Authenticated outbound HTTPS client for the current web workspace."""
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from runtime_support import BridgeError, NoRedirect

STATE = Path(__file__).resolve().parent / '.local'


class API:
    def __init__(self, config):
        self.url = config['url']
        parsed = urllib.parse.urlparse(self.url)
        if (parsed.scheme != 'https' or not parsed.hostname or
                not parsed.hostname.endswith('.apigw.yandexcloud.net') or parsed.path or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise BridgeError('Invalid cloud endpoint')
        path = Path(config['key_file'])
        if path.stat().st_mode & 0o077:
            raise BridgeError('Client key file must have mode 0600')
        lines = [x.split('=', 1)[1] for x in path.read_text().splitlines() if x.startswith('BRIDGE_CLIENT_KEY=')]
        if len(lines) != 1 or len(lines[0]) < 32:
            raise BridgeError('Invalid client key file')
        self.key = lines[0]

    def call(self, path, body):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise Conflict() from None
            raise BridgeError('Cloud HTTP ' + str(exc.code) + '; details hidden') from None
        except (OSError, ValueError):
            raise BridgeError('Cloud request failed; secrets hidden') from None


class Conflict(BridgeError):
    pass


