"""JSON-RPC client for an already running, owner-only local App Server.

Never starts a server, changes desktop configuration, or answers approvals.
"""
import asyncio
from collections import deque
import json
import os
from pathlib import Path
import stat

from bridge import BridgeError


class SharedRPC:
    def __init__(self, socket, timeout=30):
        self.socket = Path(socket)
        self.timeout = timeout
        self.ws = None
        self.sequence = 0
        self.notifications = deque()

    async def __aenter__(self):
        from websockets.asyncio.client import unix_connect
        info = self.socket.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise BridgeError('App Server socket is not owned by this user')
        if info.st_mode & 0o077:
            raise BridgeError('App Server socket permissions are too broad')
        self.ws = await unix_connect(str(self.socket), uri='ws://localhost/rpc',
                                     compression=None, open_timeout=self.timeout)
        try:
            await self.call('initialize', {
                'clientInfo': {'name': 'workspace_bridge', 'version': '0.1'},
                'capabilities': {'experimentalApi': True}})
            await self.ws.send(json.dumps({'method': 'initialized'}))
        except BaseException:
            await self.ws.close()
            raise
        return self

    async def __aexit__(self, *exc):
        await self.ws.close()

    async def receive(self):
        message = json.loads(await self.ws.recv())
        if not isinstance(message, dict):
            raise BridgeError('Invalid App Server response')
        if 'method' in message and 'id' in message:
            # Never grant approvals or fabricate answers on behalf of the owner.
            raise BridgeError('App Server requires interactive input; use desktop')
        return message

    def remember(self, message):
        # Retain only completion signals needed if they precede a start response.
        # Tool output, reasoning, and token deltas are neither buffered nor logged.
        if message.get('method') == 'turn/completed':
            if len(self.notifications) >= 256:
                raise BridgeError('Too many unconsumed completion events')
            self.notifications.append(message)

    async def call(self, method, params):
        self.sequence += 1
        ident = self.sequence
        await self.ws.send(json.dumps({'id': ident, 'method': method, 'params': params}))
        async with asyncio.timeout(self.timeout):
            while True:
                message = await self.receive()
                if message.get('id') == ident:
                    if 'error' in message:
                        raise BridgeError('App Server rejected '+method+'; details hidden')
                    if 'result' not in message:
                        raise BridgeError('Missing App Server result')
                    return message['result']
                self.remember(message)

    async def wait_completed(self, thread, turn, timeout=120):
        async with asyncio.timeout(timeout):
            while True:
                if self.notifications:
                    message = self.notifications.popleft()
                else:
                    message = await self.receive()
                params = message.get('params', {})
                if (message.get('method') == 'turn/completed' and
                        params.get('threadId') == thread and
                        params.get('turn', {}).get('id') == turn):
                    return params['turn']
