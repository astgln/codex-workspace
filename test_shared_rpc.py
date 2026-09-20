import asyncio
import json
import unittest

from bridge import BridgeError
from shared_rpc import SharedRPC


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def recv(self):
        return json.dumps(next(self.messages))


class RPCTests(unittest.IsolatedAsyncioTestCase):
    def client(self, messages):
        client = SharedRPC('/unused')
        client.ws = Socket(messages)
        return client

    async def test_completion_before_start_reply_is_retained(self):
        done = {'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'completed'}}}
        client = self.client([
            {'method':'item/reasoning/textDelta','params':{'text':'PRIVATE'}},
            done, {'id':1,'result':{'turn':{'id':'turn'}}}])
        self.assertEqual(await client.call('turn/start',{}),{'turn':{'id':'turn'}})
        self.assertEqual(len(client.notifications),1)
        self.assertEqual(await client.wait_completed('thread','turn'),done['params']['turn'])

    async def test_error_details_are_not_exposed(self):
        client = self.client([{'id':1,'error':{'message':'SECRET'}}])
        with self.assertRaisesRegex(BridgeError,'details hidden') as error:
            await client.call('thread/read',{})
        self.assertNotIn('SECRET',str(error.exception))

    async def test_interactive_request_is_not_approved(self):
        client = self.client([{'id':50,'method':'item/commandExecution/requestApproval','params':{}}])
        with self.assertRaisesRegex(BridgeError,'interactive input'):
            await client.call('turn/start',{})
        self.assertEqual(len(client.ws.sent),1)

    async def test_unrelated_completion_cannot_finish_request(self):
        client = self.client([
            {'method':'turn/completed','params':{'threadId':'other','turn':{'id':'turn'}}},
            {'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'new'}}}])
        self.assertEqual((await client.wait_completed('thread','new'))['id'],'new')
