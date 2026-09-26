"""Standalone HTTP service; no Codex credentials or command execution here."""
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import time
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from codex_workspace.domain import workspace, domain
from . import api
from .store import Store
from . import files, sessions, push, encryption_mode, device_auth
from .http_security import LoginBudget, secure_headers

store = None


async def clean_files():
    while True:
        await run_in_threadpool(files.cleanup, store)
        await asyncio.sleep(3600)


async def deliver_push(stop):
    while not stop.is_set():
        try:
            mode=encryption_mode.read(store)
            if mode is not None:
                from . import encrypted_push
                await run_in_threadpool(encrypted_push.tick,store,os.environ['OWNER_USERNAME'],mode)
        except Exception:pass  # Never log subscription endpoints or keys.
        try:await asyncio.wait_for(stop.wait(),10)
        except asyncio.TimeoutError:pass


@asynccontextmanager
async def lifespan(app):
    global store
    config_path = os.environ.get('WORKSPACE_CONFIG')
    if config_path:
        config = json.loads(Path(config_path).read_text())
        for key in ('OWNER_USERNAME','CLIENT_KEY_HASH','PROJECT_ID','PUBLIC_ORIGIN'):
            os.environ[key] = config[key]
    for key in ('OWNER_USERNAME','CLIENT_KEY_HASH','PROJECT_ID','PUBLIC_ORIGIN'):
        if not os.environ.get(key):
            raise RuntimeError('Missing service configuration')
    store = Store(os.environ.get('WORKSPACE_DATA','/var/lib/codex-workspace'))
    sessions.upgrade_auth_trust(store)
    sessions.connection(store).close()
    app.state.login_budget = LoginBudget()
    push.initialize(store)
    task = asyncio.create_task(clean_files())
    push_stop = asyncio.Event()
    notifications = asyncio.create_task(deliver_push(push_stop))
    yield
    push_stop.set()
    await notifications
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)


@app.middleware('http')
async def security_boundary(request, call_next):
    wait = app.state.login_budget.take(request.url.path.lstrip('/'))
    if wait:
        response = Response('{"error":"rate_limited"}', status_code=429,
                            media_type='application/json', headers={'Retry-After': str(wait)})
    else:
        response = await call_next(request)
    return secure_headers(response, request.url.path)


@app.api_route('/{path:path}', methods=['GET','POST','PUT','DELETE','PATCH','OPTIONS','HEAD'])
async def handle(request: Request, path: str):
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > 100000:
            return Response(status_code=413)
    event = {'path':'/'+path, 'httpMethod':request.method, 'headers':dict(request.headers),
             'body':base64.b64encode(body).decode(), 'isBase64Encoded':True}
    cookie=None
    try:
        mode=encryption_mode.read(store)
    except (OSError,ValueError):
        return Response('{"error":"encryption_mode_unavailable"}',status_code=503,media_type='application/json')
    if not encryption_mode.permitted(path):
        return Response('{"error":"encrypted_channel_required"}',status_code=409,media_type='application/json')
    try:
        if path=='auth/session':
            if request.method!='GET':return Response(status_code=405)
            uid,csrf=sessions.verify(store,request.cookies.get(sessions.COOKIE))
            if mode is None:
                return Response('{"error":"encryption_not_initialized"}',status_code=503,media_type='application/json')
            else:
                owner=uid==(await run_in_threadpool(device_auth.current,store))['owner']
                view={'user':{'id':uid},'encryption':mode,
                      'projects':[],'threads':[],'messages':[],'collector_seen':None,'catalog_updated':None}
            return Response(json.dumps({'csrf':csrf,'workspace':view}),media_type='application/json',headers={'Cache-Control':'no-store'})
        if path=='auth/logout':
            if request.method!='POST':return Response(status_code=405)
            token=request.cookies.get(sessions.COOKIE)
            uid,csrf=sessions.verify(store,token)
            sessions.check_csrf(request,csrf,os.environ['PUBLIC_ORIGIN'])
            await run_in_threadpool(sessions.revoke,store,token)
            response=Response('{"ok":true}',media_type='application/json',headers={'Cache-Control':'no-store'})
            response.delete_cookie(sessions.COOKIE,path='/',secure=True,httponly=True,samesite='lax')
            return response
        anonymous = path in ('auth/device/challenge','auth/device/session','auth/pairing/offer','auth/pairing/read')
        if anonymous:
            if request.method!='POST':return Response(status_code=405)
            if request.headers.get('origin')!=os.environ['PUBLIC_ORIGIN']:raise workspace.Forbidden()
        elif path.startswith('web/'):
            uid,csrf=sessions.verify(store,request.cookies.get(sessions.COOKIE))
            sessions.check_csrf(request,csrf,os.environ['PUBLIC_ORIGIN'])
    except workspace.Unauthorized:
        return Response('{"error":"login_required"}',status_code=401,media_type='application/json',headers={'Cache-Control':'no-store'})
    except workspace.Forbidden:
        return Response('{"error":"access_denied"}',status_code=403,media_type='application/json',headers={'Cache-Control':'no-store'})
    if path == 'health':
        result = api.response(200,{'status':'ok','mode':'standalone-web'})
    elif path in ('auth/device/challenge','auth/device/session','v2/e2ee/auth/registry'):
        try:
            if request.method!='POST':return Response(status_code=405)
            data=json.loads(body)
            if path=='v2/e2ee/auth/registry':
                if not api.authorized(event):raise workspace.Unauthorized()
                value=await run_in_threadpool(device_auth.registry,store,data,os.environ['PUBLIC_ORIGIN'])
            elif path=='auth/device/challenge':
                value=await run_in_threadpool(device_auth.challenge,store,data,os.environ['PUBLIC_ORIGIN'])
            else:
                uid,device=await run_in_threadpool(device_auth.authenticate,store,data,os.environ['PUBLIC_ORIGIN'])
                cookie,_=await run_in_threadpool(sessions.issue,store,uid,device)
                value={'ok':True,'uid':uid}
            result=api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'device_login_required'})
        except Exception:result=api.response(400,{'error':'invalid_device_authentication'})
    elif path.startswith(('web/e2ee/pairing/','v2/e2ee/pairing/','auth/pairing/')):
        from . import opaque, pairing
        try:
            if request.method != 'POST':return Response(status_code=405)
            collector = path.startswith('v2/')
            if collector:
                if not api.authorized(event):raise workspace.Unauthorized()
            value = await run_in_threadpool(pairing.handle,store,path.rsplit('/',1)[1],json.loads(body),collector=collector)
            result=api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'login_required'})
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except opaque.Conflict:result=api.response(409,{'error':'pairing_conflict'})
        except (ValueError,TypeError,RecursionError):result=api.response(400,{'error':'invalid_pairing'})
        except Exception:result=api.response(503,{'error':'temporarily_unavailable'})
    elif path.startswith('web/e2ee/files/') or path.startswith('v2/e2ee/files/'):
        from . import opaque, opaque_files
        try:
            if request.method != 'POST':return Response(status_code=405)
            collector = path.startswith('v2/')
            if collector:
                if not api.authorized(event):raise workspace.Unauthorized()
                file_uid = None
            else:
                allowed = uid == (await run_in_threadpool(device_auth.current,store))['owner']
                if not allowed:raise workspace.Forbidden()
                file_uid = uid
            value = await run_in_threadpool(opaque_files.handle,store,file_uid,path.rsplit('/',1)[1],json.loads(body),collector=collector)
            result=api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'login_required'})
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except opaque.Conflict:result=api.response(409,{'error':'encrypted_file_conflict'})
        except (ValueError,TypeError,RecursionError):result=api.response(400,{'error':'invalid_encrypted_file'})
        except Exception:result=api.response(503,{'error':'temporarily_unavailable'})
    elif path in ('web/e2ee/send', 'web/e2ee/read', 'v2/e2ee/publish', 'v2/e2ee/publish-batch', 'v2/e2ee/read'):
        from . import opaque
        try:
            if request.method != 'POST':return Response(status_code=405)
            collector = path.startswith('v2/')
            if collector:
                if not api.authorized(event):raise workspace.Unauthorized()
            else:
                # Only the pinned account may access opaque records.
                allowed = uid == (await run_in_threadpool(device_auth.current,store))['owner']
                if not allowed:raise workspace.Forbidden()
            data = json.loads(body)
            operation = opaque.read if path.endswith('/read') else opaque.publish
            if path=='v2/e2ee/publish-batch':
                value=await run_in_threadpool(opaque.publish_batch,store,data)
            else:
                value = await run_in_threadpool(operation, store, data, browser=not collector)
            result = api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'login_required'})
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except opaque.CapacityExceeded:result=api.response(507,{'error':'encrypted_storage_full'})
        except opaque.Conflict:result=api.response(409,{'error':'encrypted_conflict'})
        except (ValueError,TypeError,RecursionError):result=api.response(400,{'error':'invalid_encrypted_record'})
        except Exception:result=api.response(503,{'error':'temporarily_unavailable'})
    elif path.startswith('web/e2ee/push/'):
        try:
            if request.method!='POST':return Response(status_code=405)
            data=json.loads(body)
            if not isinstance(data,dict):raise ValueError()
            value=await run_in_threadpool(push.handle,store,uid,os.environ['OWNER_USERNAME'],path.rsplit('/',1)[1],data)
            result=api.response(200,value)
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except (ValueError,TypeError,domain.Rejected):result=api.response(400,{'error':'invalid_push'})
    elif path.startswith(('web/','v2/','auth/')):
        result = api.response(404,{'error':'not_found'})
    else:
        result = await run_in_threadpool(api.website,event,None)
    payload = base64.b64decode(result['body']) if result.get('isBase64Encoded') else result['body']
    headers = {**result.get('headers',{}),'X-Content-Type-Options':'nosniff'}
    response=Response(content=payload,status_code=result['statusCode'],headers=headers)
    if cookie:response.set_cookie(sessions.COOKIE,cookie,max_age=sessions.TTL,path='/',secure=True,httponly=True,samesite='lax')
    return response
