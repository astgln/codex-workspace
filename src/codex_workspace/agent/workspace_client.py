"""Authenticated outbound HTTPS client for the current web workspace."""
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from codex_workspace.agent.runtime_support import BridgeError, NoRedirect

from codex_workspace.paths import state_directory
STATE = state_directory()
MAX_RESPONSE_BYTES = 1024 * 1024


class API:
    def __init__(self, config, *, state=None):
        self.state = STATE if state is None else Path(state)
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
        from codex_workspace.agent.encryption_mode import encrypted_required
        if encrypted_required(getattr(self,'state',STATE)) and not (isinstance(path,str) and path.startswith('/v2/e2ee/')):
            raise BridgeError('Plaintext transport disabled by local encryption pin')
        if (not isinstance(path, str) or not path.startswith('/v2/')
                or any(character in path for character in ('?', '#', '@', '\\'))
                or any(ord(character) < 33 for character in path)):
            raise BridgeError('Invalid API path')
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise BridgeError('Cloud response exceeds size limit')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise BridgeError('Invalid cloud response')
                return result
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise Conflict() from None
            raise BridgeError('Cloud HTTP ' + str(exc.code) + '; details hidden') from None
        except (OSError, ValueError, RecursionError):
            raise BridgeError('Cloud request failed; secrets hidden') from None


class Conflict(BridgeError):
    pass


