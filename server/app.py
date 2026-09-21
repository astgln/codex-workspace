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
from cloud import login, workspace, domain
from . import api
from .store import Store
from . import files, history, sessions, push, diagnostics
from .http_security import LoginBudget, secure_headers

store = None


async def refresh_login_keys():
    while True:
        try:
            keys = await run_in_threadpool(login.public_keys, True)
            now = int(time.time())
            await run_in_threadpool(store.mutate, lambda state: login.cache_keys(state,{'keys':keys,'fetched_at':now},now))
        except Exception:
            # Never log request bodies or provider errors containing credentials.
            pass
        await run_in_threadpool(files.cleanup, store)
        await asyncio.sleep(3600)


async def deliver_push(stop):
    while not stop.is_set():
        try:await run_in_threadpool(push.tick,store,os.environ['OWNER_USERNAME'])
        except Exception:pass  # Never log subscription endpoints or keys.
        try:await asyncio.wait_for(stop.wait(),10)
        except asyncio.TimeoutError:pass


@asynccontextmanager
async def lifespan(app):
    global store
    config_path = os.environ.get('WORKSPACE_CONFIG')
    if config_path:
        config = json.loads(Path(config_path).read_text())
        for key in ('TELEGRAM_BOT_TOKEN','OWNER_USERNAME','CLIENT_KEY_HASH','PROJECT_ID','PUBLIC_ORIGIN'):
            os.environ[key] = config[key]
    for key in ('TELEGRAM_BOT_TOKEN','OWNER_USERNAME','CLIENT_KEY_HASH','PROJECT_ID','PUBLIC_ORIGIN'):
        if not os.environ.get(key):
            raise RuntimeError('Missing service configuration')
    store = Store(os.environ.get('WORKSPACE_DATA','/var/lib/codex-workspace'))
    sessions.upgrade_auth_trust(store)
    app.state.login_budget = LoginBudget()
    push.initialize(store)
    task = asyncio.create_task(refresh_login_keys())
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
        if path=='auth/session':
            if request.method!='GET':return Response(status_code=405)
            uid,csrf=sessions.verify(store,request.cookies.get(sessions.COOKIE))
            view=await run_in_threadpool(store.mutate,lambda state:workspace.view(state,uid,os.environ['OWNER_USERNAME'],int(time.time())))
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
        if path=='web/login/session':
            if request.headers.get('origin')!=os.environ['PUBLIC_ORIGIN']:raise workspace.Forbidden()
        elif path.startswith('web/') and path!='web/login/config':
            uid,csrf=sessions.verify(store,request.cookies.get(sessions.COOKIE))
            sessions.check_csrf(request,csrf,os.environ['PUBLIC_ORIGIN'])
            await run_in_threadpool(store.mutate,lambda state:workspace.is_owner(state,uid,os.environ['OWNER_USERNAME']))
            # The pure API uses an internal signed identity. Browser requests
            # authenticate only with the opaque HttpOnly cookie and CSRF token.
            event['headers']['authorization']='Workspace '+workspace.issue_session(uid,os.environ['TELEGRAM_BOT_TOKEN'],int(time.time()))
    except workspace.Unauthorized:
        return Response('{"error":"login_required"}',status_code=401,media_type='application/json',headers={'Cache-Control':'no-store'})
    except workspace.Forbidden:
        return Response('{"error":"access_denied"}',status_code=403,media_type='application/json',headers={'Cache-Control':'no-store'})
    if path == 'health':
        result = api.response(200,{'status':'ok','mode':'standalone-web'})
    elif path.startswith('web/e2ee/files/') or path.startswith('v2/e2ee/files/'):
        from . import opaque, opaque_files
        try:
            if request.method != 'POST':return Response(status_code=405)
            collector = path.startswith('v2/')
            if collector:
                if not api.authorized(event):raise workspace.Unauthorized()
                file_uid = None
            else:
                allowed = await run_in_threadpool(store.mutate, lambda state: workspace.is_owner(state,uid,os.environ['OWNER_USERNAME']))
                if not allowed:raise workspace.Forbidden()
                file_uid = uid
            value = await run_in_threadpool(opaque_files.handle,store,file_uid,path.rsplit('/',1)[1],json.loads(body),collector=collector)
            result=api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'login_required'})
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except opaque.Conflict:result=api.response(409,{'error':'encrypted_file_conflict'})
        except (ValueError,TypeError,RecursionError):result=api.response(400,{'error':'invalid_encrypted_file'})
        except Exception:result=api.response(503,{'error':'temporarily_unavailable'})
    elif path in ('web/e2ee/send', 'web/e2ee/read', 'v2/e2ee/publish', 'v2/e2ee/read'):
        from . import opaque
        try:
            if request.method != 'POST':return Response(status_code=405)
            collector = path.startswith('v2/')
            if collector:
                if not api.authorized(event):raise workspace.Unauthorized()
            else:
                # Only the pinned account may access opaque records.
                allowed = await run_in_threadpool(store.mutate, lambda state: workspace.is_owner(state,uid,os.environ['OWNER_USERNAME']))
                if not allowed:raise workspace.Forbidden()
            data = json.loads(body)
            operation = opaque.read if path.endswith('/read') else opaque.publish
            value = await run_in_threadpool(operation, store, data, browser=not collector)
            result = api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'login_required'})
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except opaque.Conflict:result=api.response(409,{'error':'encrypted_conflict'})
        except (ValueError,TypeError,RecursionError):result=api.response(400,{'error':'invalid_encrypted_record'})
        except Exception:result=api.response(503,{'error':'temporarily_unavailable'})
    elif path == 'web/diagnostics':
        if request.method != 'POST':return Response(status_code=405)
        try:
            value=await run_in_threadpool(diagnostics.inspect,store,uid,os.environ['OWNER_USERNAME'])
            result=api.response(200,value)
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
    elif path.startswith('web/push/'):
        try:
            if request.method!='POST':return Response(status_code=405)
            data=json.loads(body)
            if not isinstance(data,dict):raise ValueError()
            value=await run_in_threadpool(push.handle,store,uid,os.environ['OWNER_USERNAME'],path.rsplit('/',1)[1],data)
            result=api.response(200,value)
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except (ValueError,TypeError,domain.Rejected):result=api.response(400,{'error':'invalid_push'})
    elif path == 'v2/usage':
        from cloud.quota import valid
        if request.method != 'POST':return Response(status_code=405)
        if not api.authorized(event):return Response(status_code=401)
        try:
            data=json.loads(body)
            if not valid(data) or data['observed_at'] > time.time()+60:raise ValueError()
            def save_usage(state):
                if data['observed_at'] >= state.get('weekly_quota', {}).get('observed_at', 0):
                    state['weekly_quota']=data
                return {'ok':True}
            value=await run_in_threadpool(store.mutate,save_usage)
            result=api.response(200,value)
        except (ValueError,TypeError):result=api.response(400,{'error':'invalid_request'})
    elif path in ('web/history','v2/history/pending','v2/history/publish'):
        try:
            if request.method!='POST':return Response(status_code=405)
            data=json.loads(body)
            if not isinstance(data,dict):raise ValueError()
            collector=path.startswith('v2/')
            if collector:
                if not api.authorized(event):raise workspace.Unauthorized()
                uid=None
            else:
                authorization=event['headers'].get('authorization','')
                if not authorization.startswith('Workspace '):raise workspace.Unauthorized()
                uid=workspace.verify_session(authorization[10:],os.environ['TELEGRAM_BOT_TOKEN'],int(time.time()))
            value=await run_in_threadpool(history.handle,store,uid,os.environ['OWNER_USERNAME'],'read' if not collector else path.rsplit('/',1)[1],data,collector)
            result=api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'login_required'})
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except domain.Rejected:result=api.response(409,{'error':'history_conflict'})
        except (ValueError,TypeError):result=api.response(400,{'error':'invalid_request'})
        except Exception:result=api.response(503,{'error':'temporarily_unavailable'})
    elif path.startswith('web/uploads/') or path == 'v2/files/get':
        try:
            if request.method!='POST':
                return Response(status_code=405)
            data=json.loads(body)
            if not isinstance(data,dict):raise ValueError()
            collector=path=='v2/files/get'
            if collector:
                if not api.authorized(event):raise workspace.Unauthorized()
                uid=None
            else:
                authorization=event['headers'].get('authorization','')
                if not authorization.startswith('Workspace '):raise workspace.Unauthorized()
                uid=workspace.verify_session(authorization[10:],os.environ['TELEGRAM_BOT_TOKEN'],int(time.time()))
            value=await run_in_threadpool(files.handle,store,uid,os.environ['OWNER_USERNAME'],path.rsplit('/',1)[1],data,collector)
            result=api.response(200,value)
        except workspace.Unauthorized:result=api.response(401,{'error':'login_required'})
        except workspace.Forbidden:result=api.response(403,{'error':'access_denied'})
        except domain.Rejected:result=api.response(409,{'error':'upload_conflict'})
        except (ValueError,TypeError):result=api.response(400,{'error':'invalid_request'})
        except Exception:result=api.response(503,{'error':'temporarily_unavailable'})
    elif path.startswith('web/'):
        result = await run_in_threadpool(api.web_api,event,None,mutate=store.mutate)
        if path=='web/login/session' and result['statusCode']==200:
            signed=json.loads(result['body'])['token']
            uid=workspace.verify_session(signed,os.environ['TELEGRAM_BOT_TOKEN'],int(time.time()))
            cookie,_=await run_in_threadpool(sessions.issue,store,uid)
            result=api.response(200,{'ok':True})
    elif path.startswith('v2/'):
        result = await run_in_threadpool(api.api,event,None,mutate=store.mutate)
    else:
        result = await run_in_threadpool(api.website,event,None)
    payload = base64.b64decode(result['body']) if result.get('isBase64Encoded') else result['body']
    headers = {**result.get('headers',{}),'X-Content-Type-Options':'nosniff'}
    response=Response(content=payload,status_code=result['statusCode'],headers=headers)
    if cookie:response.set_cookie(sessions.COOKIE,cookie,max_age=sessions.TTL,path='/',secure=True,httponly=True,samesite='lax')
    return response
