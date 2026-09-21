import { test, expect, type Page } from '@playwright/test';

async function fixture(page: Page, role: 'owner'|'member' = 'owner') {
  const threads = [{id:'thread-launcher',title:'Launcher',status:'idle'}, {id:'thread-hd',title:'HD',status:'idle'}];
  const state = {weekly_quota:{used_percent:63,observed_at:Math.floor(Date.now()/1000),resets_at:Math.floor(Date.now()/1000)+86400},user:{id:role==='owner'?10:20,role},threads,messages:[] as any[],members:[{id:20,username:'friend',requires_approval:true,threads:[]}],catalog_updated:1,collector_seen:Date.now()/1000};
  const sent:any[] = [], decisions:any[] = [];
  let loggedIn=false;
  await page.route('**/auth/**',route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/auth/logout'){loggedIn=false;return route.fulfill({json:{ok:true}});}
    return loggedIn?route.fulfill({json:{csrf:'test-csrf',workspace:state}}):route.fulfill({status:401,json:{error:'login_required'}});
  });
  // Only this test browser intercepts auth. The production API has no test mode.
  await page.context().route('https://oauth.telegram.org/auth?*', route => {
    const url=new URL(route.request().url());
    expect(url.searchParams.get('origin')).toBe('http://127.0.0.1:5173');
    return route.fulfill({contentType:'text/html',body:`<script>opener.postMessage({event:'auth_result',result:'test-browser-token'},'http://127.0.0.1:5173')</script>`});
  });
  await page.route('**/web/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().method()==='POST' ? route.request().postDataJSON() : {};
    let output:unknown = {};
    if(path==='/web/login/config')output={client_id:'123',nonce:'test-nonce',challenge:'test-challenge'};
    else if(path==='/web/login/session'){loggedIn=true;output={ok:true};}
    else if(path==='/web/state')output=state;
    else if(path==='/web/diagnostics')output={worker:{status:'waiting_for_tasks',observed_at:1,waiting:{desktop_writer_lock:2,task_settings_unavailable:1},unresolved:3},collector_recent:true,collector_seen:1,history_synced:1,queue:{awaiting_approval:0,approved:2},completed:5,notifications:{devices:1,retrying:0,uncertain:1}};
    else if(path==='/web/push/config')output={public_key:'test-key'};
    else if(path==='/web/history')output={messages:[],before:null,synced_at:1,loading_older:false,pending:false};
    else if(path==='/web/messages'){
      sent.push(body); const item={...body,id:-sent.length,sender:state.user.id,status:role==='owner'?'approved':'awaiting_approval',snapshot:'immutable-snapshot',created:Date.now()/1000,expires:Date.now()/1000+86400};state.messages.push(item);output=item;
    } else if(path==='/web/decisions'){
      decisions.push(body); const item=state.messages.find(m=>m.id===body.id);item.status=body.decision;output=item;
    } else if(path==='/web/member-policy')state.members[0].requires_approval=body.requires_approval;
    else if(path==='/web/grants')Object.assign(state.members[0],{threads:body.threads,projects:body.projects||[],denied_threads:body.denied_threads||[]});
    else return route.fulfill({status:404,body:'{}'});
    await route.fulfill({json:output});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Войти через Telegram'}).click();
  await expect(page.getByRole('button',{name:'Launcher',exact:true})).toBeVisible();
  return {state,sent,decisions};
}

test('drafts follow threads, sending preserves target, approval uses exact snapshot',async({page})=>{
  const f=await fixture(page);
  await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('Launcher draft');
  await page.getByRole('button',{name:'HD',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toHaveValue('');
  await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('HD draft');
  await page.getByRole('button',{name:'Launcher',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toHaveValue('Launcher draft');
  await page.getByRole('button',{name:'Отправить',exact:true}).click();
  await expect(page.getByText('Ожидает Codex',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Передать в Codex',exact:true})).toHaveCount(0);
  expect(f.decisions).toHaveLength(0);
  expect(f.sent[0]).toMatchObject({thread:'thread-launcher',text:'Launcher draft'});
  f.state.messages.push({id:-2,sender:20,thread:'thread-launcher',text:'Member request',status:'awaiting_approval',snapshot:'member-snapshot',created:Date.now()/1000});
  await page.getByRole('button',{name:'Обновить',exact:true}).click();
  await page.getByRole('button',{name:'Передать в Codex',exact:true}).click();
  await expect(page.getByText('Ожидает одобрения',{exact:true})).toHaveCount(0);
  expect(f.decisions[0]).toEqual({id:-2,snapshot:'member-snapshot',decision:'approved'});
  await page.getByRole('button',{name:'HD',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toHaveValue('HD draft');
});

test('member has no approval or access management controls',async({page})=>{
  await fixture(page,'member');
  await expect(page.getByRole('button',{name:'Доступ к тредам'})).toHaveCount(0);
  await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('Member request');
  await page.getByRole('button',{name:'Отправить',exact:true}).click();
  await expect(page.getByText('Ожидает одобрения',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Передать в Codex',exact:true})).toHaveCount(0);
});

test('mobile navigation and untrusted markdown stay in bounds',async({page})=>{
  const f=await fixture(page);
  f.state.messages.push({id:-1,sender:20,thread:'thread-launcher',text:'<script>alert(1)</script>\n![remote](https://example.com/tracker.png)',created:Date.now()/1000,status:'delivered',snapshot:'s',events:[{id:'a',type:'agent_message',text:'Ответ **Codex**'}]});
  await page.getByRole('button',{name:'Обновить',exact:true}).click();
  await expect(page.getByText('Ответ Codex')).toBeVisible();
  await expect(page.locator('img[src="https://example.com/tracker.png"]')).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Открыть треды'}).click();
  await page.getByRole('button',{name:'HD',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});

test('uploaded files remain attached to their original thread and approval payload',async({page})=>{
  const f=await fixture(page,'member');
  let attachment:any;
  await page.route('**/web/uploads/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    const body=route.request().postDataJSON();
    if(path.endsWith('/start')){attachment={id:'a'.repeat(32),name:body.name,size:body.size,sha256:body.sha256,chunk_size:49152};return route.fulfill({json:attachment});}
    if(path.endsWith('/finish'))return route.fulfill({json:attachment});
    return route.fulfill({json:{ok:true}});
  });
  await page.locator('input[type=file]').setInputFiles({name:'Connection.log',mimeType:'text/plain',buffer:Buffer.from('Example log')});
  await expect(page.getByRole('button',{name:'Убрать Connection.log'})).toBeEnabled();
  await page.getByRole('button',{name:'HD',exact:true}).click();
  await expect(page.getByRole('button',{name:'Убрать Connection.log'})).toHaveCount(0);
  await page.getByRole('button',{name:'Launcher',exact:true}).click();
  await page.getByRole('button',{name:'Отправить',exact:true}).click();
  await expect(page.getByText('Ожидает одобрения',{exact:true})).toBeVisible();
  expect(f.sent[0].attachments).toEqual(['a'.repeat(32)]);
  expect(f.sent[0].thread).toBe('thread-launcher');
});

test('login configuration failure explains failure and permits retry',async({page})=>{
  await page.route('**/web/login/config',route=>route.fulfill({status:503,json:{error:'unavailable'}}));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Сервис временно недоступен');
  await expect(page.getByRole('button',{name:'Повторить',exact:true})).toBeEnabled();
  await page.route('**/web/login/config',route=>route.fulfill({json:{client_id:'123',nonce:'nonce',challenge:'challenge'}}));
  await page.getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(page.getByRole('button',{name:'Войти через Telegram'})).toBeEnabled();
});

test('login without popup callback can be cancelled and retried',async({page})=>{
  await page.route('**/web/login/config',route=>route.fulfill({json:{client_id:'123',nonce:'nonce',challenge:'challenge'}}));
  await page.context().route('https://oauth.telegram.org/auth?*',route=>route.fulfill({contentType:'text/html',body:'Waiting for login'}));
  await page.goto('/');
  await page.getByRole('button',{name:'Войти через Telegram'}).click();
  await expect(page.getByRole('status')).toContainText('обычном браузере');
  await page.getByRole('button',{name:'Отменить вход'}).click();
  await expect(page.getByRole('alert')).toContainText('Вход отменён');
  await page.getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(page.getByRole('button',{name:'Войти через Telegram'})).toBeEnabled();
});

test('login ignores results from an unrelated window or origin',async({page})=>{
  await page.route('**/web/login/config',route=>route.fulfill({json:{client_id:'123',nonce:'nonce',challenge:'challenge'}}));
  let sessions=0;
  await page.route('**/web/login/session',route=>{sessions++;return route.fulfill({status:401,json:{error:'invalid'}});});
  await page.context().route('https://oauth.telegram.org/auth?*',route=>route.fulfill({contentType:'text/html',body:'Login'}));
  await page.goto('/');
  await page.evaluate(()=>{const open=window.open.bind(window);window.open=(...args)=>{const popup=open(...args);(window as any).__testPopup=popup;return popup;};});
  const popupPromise=page.waitForEvent('popup');
  await page.getByRole('button',{name:'Войти через Telegram'}).click();
  const popup=await popupPromise;
  await popup.waitForLoadState();
  await page.evaluate(()=>{
    window.dispatchEvent(new MessageEvent('message',{origin:'https://oauth.telegram.org',source:window,data:{event:'auth_result',result:'forged'}}));
  });
  await page.evaluate(()=>window.dispatchEvent(new MessageEvent('message',{origin:'https://unrelated.example',source:(window as any).__testPopup,data:{event:'auth_result',result:'forged'}})));
  await page.getByRole('button',{name:'Отменить вход'}).click();
  expect(sessions).toBe(0);
});

test('blocked login popup leaves an actionable error',async({page})=>{
  await page.addInitScript(()=>{window.open=()=>null;});
  await page.route('**/web/login/config',route=>route.fulfill({json:{client_id:'123',nonce:'nonce',challenge:'challenge'}}));
  await page.goto('/');
  await page.getByRole('button',{name:'Войти через Telegram'}).click();
  await expect(page.getByRole('alert')).toContainText('Браузер заблокировал окно Telegram');
  await expect(page.getByRole('button',{name:'Повторить',exact:true})).toBeEnabled();
});

test('unexpected Telegram payload diagnostic never exposes values',async({page})=>{
  await page.route('**/web/login/config',route=>route.fulfill({json:{client_id:'123',nonce:'nonce',challenge:'challenge'}}));
  await page.context().route('https://oauth.telegram.org/auth?*',route=>route.fulfill({contentType:'text/html',body:`<script>opener.postMessage({event:'auth_result',result:{id:123,username:'private-user',hash:'private-signature',auth_date:42},error:'private-error'},'http://127.0.0.1:5173')</script>`}));
  await page.goto('/');
  await page.getByRole('button',{name:'Войти через Telegram'}).click();
  const alert=page.getByRole('alert');
  await expect(alert).toContainText('result=object');
  await expect(alert).toContainText('result_fields=auth_date,hash,id,username');
  await expect(alert).not.toContainText('private-');
});


test('signed widget object is forwarded for server verification without decoding trust',async({page})=>{
  await page.route('**/web/login/config',route=>route.fulfill({json:{client_id:'123',nonce:'nonce',challenge:'challenge'}}));
  let submitted:any;
  await page.route('**/web/login/session',route=>{submitted=route.request().postDataJSON();return route.fulfill({status:401,json:{error:'forged'}});});
  await page.context().route('https://oauth.telegram.org/auth?*',route=>route.fulfill({contentType:'text/html',body:`<script>opener.postMessage({event:'auth_result',result:{id:42,username:'owner',auth_date:1000,hash:'forged'}},'http://127.0.0.1:5173')</script>`}));
  await page.goto('/');
  await page.getByRole('button',{name:'Войти через Telegram'}).click();
  await expect(page.getByRole('alert')).toContainText('Войдите снова');
  expect(submitted).toEqual({challenge:'challenge',widget_data:{id:42,username:'owner',auth_date:1000,hash:'forged'}});
  await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toHaveCount(0);
});


test('existing server session restores after reload and logout clears it',async({page})=>{
  await fixture(page);
  await page.reload();
  await expect(page.getByRole('button',{name:'Launcher',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Войти через Telegram'})).toHaveCount(0);
  await page.getByRole('button',{name:'Выйти',exact:true}).click();
  await expect(page.getByRole('button',{name:'Войти через Telegram'})).toBeEnabled();
  await page.reload();
  await expect(page.getByRole('button',{name:'Войти через Telegram'})).toBeEnabled();
});

test('shared history loads older messages and resets when changing thread',async({page})=>{
 await fixture(page);
 await page.route('**/web/history',route=>{
  const body=route.request().postDataJSON();
  const hd=body.thread==='thread-hd';
  const older=Boolean(body.before);
  return route.fulfill({json:{messages:[{id:hd?'hd':older?'old':'recent',position:older?'001':'002',role:'assistant',text:hd?'История HD':older?'Ранний ответ launcher':'Последний ответ launcher',created:older?1:2}],before:hd||older?null:'002',synced_at:1,loading_older:false,pending:false}});
 });
 await page.getByRole('button',{name:'HD',exact:true}).click();
 await expect(page.getByText('История HD',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Launcher',exact:true}).click();
 await expect(page.getByText('Последний ответ launcher',{exact:true})).toBeVisible();
 await expect(page.getByText('История HD',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Показать более ранние сообщения'}).click();
 await expect(page.getByText('Ранний ответ launcher',{exact:true})).toBeVisible();
 await expect(page.getByText('Последний ответ launcher',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Показать более ранние сообщения'}).count().then(n=>expect(n).toBe(0));
});


test('read-only task history remains readable without offering submission',async({page})=>{
 const f=await fixture(page);
 Object.assign(f.state.threads[0],{read_only:true});
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.getByText('Эта задача доступна только для чтения.',{exact:false})).toBeVisible();
 await expect(page.getByRole('button',{name:'Отправить',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'HD',exact:true}).click();
 await expect(page.getByRole('button',{name:'Отправить',exact:true})).toBeVisible();
});

test('conversation opens at end, restores reading position and anchors older history',async({page})=>{
 await fixture(page);
 await page.route('**/web/history',async route=>{
  const body=route.request().postDataJSON();const older=Boolean(body.before);const start=older?0:30;
  await route.fulfill({json:{messages:Array.from({length:30},(_,i)=>({id:body.thread+':'+(i+start),position:String(i+start).padStart(4,'0'),role:'assistant',text:`Message ${i+start}\n\n`+'Reading text. '.repeat(60),created:i+start+1})),before:older?null:'0030',synced_at:1,loading_older:false,pending:false}});
 });
 await page.getByRole('button',{name:'HD',exact:true}).click();
 const main=page.locator('.workspace-main');
 await expect(page.getByText('Message 59',{exact:false})).toBeVisible();
 await expect.poll(()=>main.evaluate(el=>Math.abs(el.scrollHeight-el.clientHeight-el.scrollTop))).toBeLessThan(3);
 await main.evaluate(el=>{el.scrollTop=800;});
 await expect.poll(()=>main.evaluate(el=>el.scrollTop)).toBe(800);
 await expect.poll(()=>page.evaluate(()=>sessionStorage.getItem('workspace-scroll:10:thread-hd'))).toContain('"bottom":false');
 await page.getByRole('button',{name:'Launcher',exact:true}).click();
 await expect.poll(()=>main.evaluate(el=>Math.abs(el.scrollHeight-el.clientHeight-el.scrollTop))).toBeLessThan(3);
 await page.getByRole('button',{name:'HD',exact:true}).click();
 await expect.poll(()=>main.evaluate(el=>Math.round(el.scrollTop))).toBe(800);
 await main.evaluate(el=>{el.scrollTop=0;});
 await expect.poll(()=>page.evaluate(()=>JSON.parse(sessionStorage.getItem('workspace-scroll:10:thread-hd')||'{}').top)).toBe(0);
 const anchor=page.locator('[data-scroll-id="history:thread-hd:30"]');const y=await anchor.evaluate(el=>el.getBoundingClientRect().top);
 await page.getByRole('button',{name:'Показать более ранние сообщения'}).click();
 await expect(page.locator('[data-scroll-id="history:thread-hd:0"]')).toBeAttached();
 await expect.poll(()=>anchor.evaluate(el=>el.getBoundingClientRect().top)).toBeCloseTo(y,0);
 const olderAnchor=page.locator('[data-scroll-id="history:thread-hd:5"]');
 await olderAnchor.evaluate(el=>{const main=el.closest('main')!;main.scrollTop+=el.getBoundingClientRect().top-main.getBoundingClientRect().top+40;});
 await expect.poll(()=>page.evaluate(()=>JSON.parse(sessionStorage.getItem('workspace-scroll:10:thread-hd')||'{}').anchor)).toBe('history:thread-hd:5');
 const oldY=await olderAnchor.evaluate(el=>el.getBoundingClientRect().top);
 await page.reload();
 await page.getByRole('button',{name:'HD',exact:true}).click();
 await expect(olderAnchor).toBeAttached();
 await expect.poll(()=>olderAnchor.evaluate(el=>el.getBoundingClientRect().top)).toBeCloseTo(oldY,0);
});

 test('weekly quota includes observation time',async({page})=>{
  await fixture(page);
  await expect(page.getByText('Неделя: 37% осталось')).toBeVisible();
  await expect(page.getByLabel('Остаток недельной квоты')).toHaveAttribute('value','37');
  await expect(page.getByText(/^Данные на /)).toBeVisible();
 });
 test('members see shared account quota',async({page})=>{
  await fixture(page,'member');
  await expect(page.getByText('Неделя: 37% осталось')).toBeVisible();
 });

test('PWA manifest, worker and iPhone installation instructions',async({page})=>{
 await page.addInitScript(()=>{Object.defineProperty(navigator,'userAgent',{get:()=> 'iPhone'});});
 await fixture(page);
 await page.getByText('Приложение и уведомления',{exact:true}).click();
 await expect(page.getByText(/На iPhone: Safari/)).toBeVisible();
 await expect(page.getByText(/iOS 16.4/)).toBeVisible();
 await expect(page.getByRole('button',{name:'Включить уведомления',exact:true})).toHaveCount(0);
 const manifest=await (await page.request.get('/manifest.webmanifest')).json();
 expect(manifest.display).toBe('standalone');expect(manifest.start_url).toBe('/');
 expect((await page.request.get('/sw.js')).ok()).toBeTruthy();
});
test('notification link opens permitted task',async({page})=>{
 await fixture(page);
 await page.evaluate(()=>{location.hash='thread=thread-hd';});
 await expect(page.locator('.header-title strong')).toHaveText('HD');
 await page.evaluate(()=>{location.hash='approvals';});
 await expect(page.locator('.header-title strong')).toHaveText('Одобрения');
});

test('owner controls approval independently of task access',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'Доступ к тредам',exact:true}).click();
 const toggle=page.getByRole('checkbox',{name:'Требовать одобрение запросов',exact:true});
 await expect(toggle).toBeChecked();await toggle.click();await expect(toggle).not.toBeChecked();
 expect(f.state.members[0].requires_approval).toBe(false);
 expect(f.state.members[0].threads).toEqual([]);
 await expect(page.getByText('Новые запросы сразу попадают в очередь Codex.')).toBeVisible();
 await toggle.click();await expect(toggle).toBeChecked();
});

test('project switch filters tasks and updates breadcrumb',async({page})=>{
 const f=await fixture(page);
 Object.assign(f.state,{projects:[{id:'warcraft',title:'Warcraft'},{id:'second',title:'Second'},{id:'empty',title:'Empty'}]});
 f.state.threads.forEach(t=>Object.assign(t,{project_id:'warcraft'}));
 f.state.threads.push({id:'thread-second',title:'Second task',status:'idle',project_id:'second'} as any);
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await page.getByLabel('Проект',{exact:true}).selectOption('second');
 await expect(page.getByRole('button',{name:'Launcher',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Открыть проект Second',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Second task',exact:true}).first().click();
 await expect(page.locator('.header-title strong')).toHaveText('Second task');
 await page.getByLabel('Проект',{exact:true}).selectOption('empty');
 await expect(page.getByRole('heading',{name:'Empty',exact:true})).toBeVisible();
});

test('project access with task exclusion and independent task grant',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'Доступ к тредам',exact:true}).click();
 const project=page.getByRole('checkbox',{name:'Весь проект Warcraft для @friend',exact:true});
 const launcher=page.getByRole('checkbox',{name:'Launcher для @friend',exact:true});
 const hd=page.getByRole('checkbox',{name:'HD для @friend',exact:true});
 await project.click();await expect(project).toBeChecked();await expect(launcher).toBeChecked();await expect(hd).toBeChecked();
 await hd.click();await expect(hd).not.toBeChecked();await expect(launcher).toBeChecked();
 await expect(page.getByText('HD · закрыта',{exact:true})).toBeVisible();
 await project.click();await expect(project).not.toBeChecked();await expect(launcher).not.toBeChecked();
 await launcher.click();await expect(launcher).toBeChecked();await expect(hd).not.toBeChecked();
 expect(f.state.members[0].threads).toEqual(['thread-launcher']);
});

test('request activity follows queue running completion and offline states',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('Status feedback');
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 await expect(page.getByText('В очереди Codex…',{exact:true})).toBeVisible();
 const message=f.state.messages[0];message.status='delivered';
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.getByText('Ожидаю ответа Codex…',{exact:true})).toBeVisible();
 message.result_status='running';
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.getByText('Думаю…',{exact:true})).toBeVisible();
 f.state.collector_seen=0;
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.getByText('Ожидаю подключения Codex…',{exact:true})).toBeVisible();
 message.result_status='completed';
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.locator('.request-activity')).toHaveCount(0);
});

test('member activity waits for approval without claiming execution',async({page})=>{
 await fixture(page,'member');
 await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('Needs approval');
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 await expect(page.getByText('Ожидаю одобрения…',{exact:true})).toBeVisible();
 await expect(page.getByText('Думаю…',{exact:true})).toHaveCount(0);
});

test('activity text shimmers and respects reduced motion',async({page})=>{
 await fixture(page);
 await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('Shimmer feedback');
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 const text=page.locator('.request-activity-text');
 await expect(text).toHaveCSS('animation-name','request-shimmer');
 await page.emulateMedia({reducedMotion:'reduce'});
 await expect(text).toHaveCSS('animation-name','none');
 await expect(text).toBeVisible();
});

test('failed submission keeps draft and idempotency key on retry',async({page})=>{
 const f=await fixture(page);
 const attempts:any[]=[];
 await page.route('**/web/messages',route=>{
  attempts.push(route.request().postDataJSON());
  if(attempts.length===1)return route.fulfill({status:503,json:{error:'unavailable'}});
  return route.fallback();
 });
 await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('Retry safely');
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 await expect(page.getByRole('alert')).toBeVisible();
 await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toHaveValue('Retry safely');
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 await expect(page.getByText('В очереди Codex…',{exact:true})).toBeVisible();
 expect(attempts).toHaveLength(2);
 expect(attempts[0].request_id).toBe(attempts[1].request_id);
 expect(f.sent).toHaveLength(1);
});

test('owner diagnostics shows service counters',async({page})=>{
 await fixture(page);
 await page.getByText('Состояние сервиса',{exact:true}).click();
 await expect(page.getByText('Обработчик на связи',{exact:true})).toBeVisible();
 await expect(page.getByText('Занятых задач: 2',{exact:false})).toBeVisible();
 await expect(page.getByText('Требуют сверки: 3',{exact:false})).toBeVisible();
 await expect(page.getByText('Неопределённые отправки не повторяются автоматически.',{exact:false})).toBeVisible();
});

test('member has no diagnostics control',async({page})=>{
 await fixture(page,'member');
 await expect(page.getByText('Состояние сервиса',{exact:true})).toHaveCount(0);
});

test('late workspace response cannot restore a logged out session',async({page})=>{
 const f=await fixture(page);
 let release:()=>void=()=>{};
 let started:()=>void=()=>{};
 const waiting=new Promise<void>(resolve=>{started=resolve;});
 const held=new Promise<void>(resolve=>{release=resolve;});
 await page.route('**/web/state',async route=>{
  started();await held;await route.fulfill({json:f.state});
 });
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await waiting;
 await page.getByRole('button',{name:'Выйти',exact:true}).click();
 await expect(page.getByRole('button',{name:'Войти через Telegram',exact:true})).toBeVisible();
 const response=page.waitForResponse('**/web/state');
 release();await response;
 await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 await expect(page.getByRole('button',{name:'Launcher',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Войти через Telegram',exact:true})).toBeVisible();
});

test('expired session during submission clears private drafts before next login',async({page})=>{
 await fixture(page);
 await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('Private draft from expired session');
 await page.route('**/web/messages',route=>route.fulfill({status:401,json:{error:'expired'}}));
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 await page.getByRole('button',{name:'Войти через Telegram',exact:true}).click();
 await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toHaveValue('');
});

for(const delayedStage of ['start','finish'])test(`upload ${delayedStage} response cannot cross a session boundary`,async({page})=>{
 await fixture(page);
 let release:()=>void=()=>{},started:()=>void=()=>{};
 const held=new Promise<void>(resolve=>{release=resolve;});
 const waiting=new Promise<void>(resolve=>{started=resolve;});
 let attachment:any;let chunks=0;
 await page.route('**/web/uploads/**',async route=>{
  const stage=new URL(route.request().url()).pathname.split('/').pop();
  if(stage==='start'){
   const body=route.request().postDataJSON();
   attachment={id:'b'.repeat(32),name:body.name,size:body.size,sha256:body.sha256,chunk_size:49152};
  }
  if(stage==='chunk')chunks++;
  if(stage===delayedStage){started();await held;}
  await route.fulfill({json:stage==='chunk'?{ok:true}:attachment});
 });
 await page.locator('input[type=file]').setInputFiles({name:'Old-session.log',mimeType:'text/plain',buffer:Buffer.from('Old private bytes')});
 await waiting;
 await page.route('**/web/state',route=>route.fulfill({status:401,json:{error:'expired'}}));
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.getByRole('button',{name:'Войти через Telegram',exact:true})).toBeEnabled();
 await page.unroute('**/web/state');
 await page.getByRole('button',{name:'Войти через Telegram',exact:true}).click();
 await page.getByRole('textbox',{name:'Сообщение',exact:true}).fill('New session draft');
 const response=page.waitForResponse(`**/web/uploads/${delayedStage}`);
 release();await response;
 await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 await expect(page.getByRole('button',{name:'Убрать Old-session.log'})).toHaveCount(0);
 await expect(page.getByRole('textbox',{name:'Сообщение',exact:true})).toHaveValue('New session draft');
 if(delayedStage==='start')expect(chunks).toBe(0);
});

test('notification navigation uses refreshed grants without replaying old links',async({page})=>{
 const f=await fixture(page,'member');
 f.state.threads.push({id:'thread-new',title:'Newly granted',status:'idle'});
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.getByRole('button',{name:'Newly granted',exact:true})).toBeVisible();
 await page.evaluate(()=>{location.hash='thread=thread-new';});
 await expect(page.locator('.header-title strong')).toHaveText('Newly granted');
 await page.getByRole('button',{name:'HD',exact:true}).click();
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.locator('.header-title strong')).toHaveText('HD');
 f.state.threads.splice(f.state.threads.findIndex(t=>t.id==='thread-hd'),1);
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.locator('.header-title strong')).toHaveText('Launcher');
 await page.evaluate(()=>{location.hash='thread=thread-hd';});
 await expect(page.locator('.header-title strong')).toHaveText('Launcher');
 await page.evaluate(()=>{location.hash='approvals';});
 await expect(page.locator('.header-title strong')).toHaveText('Launcher');
});
