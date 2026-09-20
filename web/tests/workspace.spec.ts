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
    else if(path==='/web/push/config')output={public_key:'test-key'};
    else if(path==='/web/history')output={messages:[],before:null,synced_at:1,loading_older:false,pending:false};
    else if(path==='/web/messages'){
      sent.push(body); const item={...body,id:-sent.length,sender:state.user.id,status:role==='owner'?'approved':'awaiting_approval',snapshot:'immutable-snapshot',created:Date.now()/1000,expires:Date.now()/1000+86400};state.messages.push(item);output=item;
    } else if(path==='/web/decisions'){
      decisions.push(body); const item=state.messages.find(m=>m.id===body.id);item.status=body.decision;output=item;
    } else if(path==='/web/member-policy')state.members[0].requires_approval=body.requires_approval;
    else if(path==='/web/grants')state.members[0].threads=body.threads;
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


test('controller history remains readable without offering self-dispatch',async({page})=>{
 const f=await fixture(page);
 Object.assign(f.state.threads[0],{read_only:true});
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await expect(page.getByText('История управляющей задачи доступна для чтения.',{exact:false})).toBeVisible();
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
