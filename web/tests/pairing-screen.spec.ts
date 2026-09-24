import {test,expect} from '@playwright/test';

test('pairing fragment is removed before session requests and errors never echo it',async({page})=>{
 const requests:string[]=[];
 await page.route('**/auth/session',async route=>{
   expect(await page.evaluate(()=>location.hash)).toBe('');
   return route.fulfill({json:{csrf:'test',workspace:{user:{id:10},threads:[],messages:[],collector_seen:null,encryption:{v:1,workspace:"A".repeat(43)}}}});
 });
 page.on('request',r=>requests.push(r.url()+' '+(r.postData()||'')));
 await page.route('**/web/**',r=>r.fulfill({json:{messages:[],pending:false}}));
 const secret='invalid-secret-never-echo';
 await page.goto('/#pair='+secret);
 await expect(page.getByRole('heading',{name:'Привязать устройство'})).toBeVisible();
 await page.getByRole('button',{name:'Привязать',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Не удалось завершить привязку');
 expect(await page.locator('body').innerText()).not.toContain(secret);
 expect(requests.some(r=>r.includes(secret))).toBe(false);
 await page.getByRole('button',{name:'Отмена',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Привязать устройство'})).toHaveCount(0);
});

for(const paste of [false,true])test(`trusted link completes pairing and persists only verified keys (paste=${paste})`,async({page})=>{
 await page.goto('/');
 const fixture=await page.evaluate(async()=>{
   // @ts-expect-error Vite test module
   const c=await import('/src/features/encryption/envelope.ts');
   const authority=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
   const invite={v:1,workspace:c.encode(crypto.getRandomValues(new Uint8Array(32))),id:c.encode(crypto.getRandomValues(new Uint8Array(32))),
     secret:c.encode(crypto.getRandomValues(new Uint8Array(32))),authority:c.encode(new Uint8Array(await crypto.subtle.exportKey('spki',authority.publicKey))),expires:Math.floor(Date.now()/1000)+600};
   return {invite,privateKey:await crypto.subtle.exportKey('jwk',authority.privateKey),fragment:'#pair='+c.encode(new TextEncoder().encode(JSON.stringify(invite)))};
 });
 // Serve the same local build through a test-only HTTPS origin for origin pinning.
 await page.route('https://workspace.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/auth/session')return route.fulfill({json:{csrf:'test',workspace:{user:{id:10},threads:[],messages:[],collector_seen:null,encryption:{v:1,workspace:fixture.invite.workspace}}}});
   if(url.pathname==='/web/e2ee/pairing/offer'){
     const offer=route.request().postDataJSON();
     expect(JSON.stringify(offer)).not.toContain(fixture.invite.secret);
     const grant=await page.evaluate(async({fixture,offer})=>{
       // @ts-expect-error Vite test module
       const c=await import('/src/features/encryption/envelope.ts');
       const privateKey=await crypto.subtle.importKey('jwk',fixture.privateKey,{name:'ECDSA',namedCurve:'P-256'},false,['sign']);
       const publicKey=await crypto.subtle.importKey('spki',c.decode(fixture.invite.authority,256),{name:'ECDSA',namedCurve:'P-256'},true,['verify']);
       const device=await crypto.subtle.importKey('spki',c.decode(offer.public_key,256),{name:'ECDSA',namedCurve:'P-256'},true,['verify']);
       const bundle={v:1,workspace:fixture.invite.workspace,origin:location.origin,device:await c.signerId(device),authority:fixture.invite.authority,revision:1,keys:[]};
       return c.seal(c.decode(fixture.invite.secret,32),{privateKey,publicKey},[fixture.invite.workspace,'devices','key-wrap',fixture.invite.id,2],new TextEncoder().encode(JSON.stringify(bundle)));
     },{fixture,offer});
     await page.route('https://workspace.test/web/e2ee/pairing/read',r=>r.fulfill({json:{payload:{envelope:grant}}}));
     return route.fulfill({json:{ok:true}});
   }
   if(url.pathname.startsWith('/web/'))return route.fulfill({json:{messages:[],pending:false}});
   return route.fulfill({response:await route.fetch({url:'http://127.0.0.1:5173'+url.pathname+url.search})});
 });
 const traffic:string[]=[];
 page.on('request',r=>traffic.push(r.url()+' '+(r.postData()||'')));
 await page.goto('https://workspace.test/'+(paste?'':fixture.fragment));
 if(paste){
  await expect(page.getByRole('heading',{name:'Привяжите это приложение'})).toBeVisible();
  await page.getByLabel('Ссылка привязки').fill('https://wrong.example/'+fixture.fragment);
  await page.getByRole('button',{name:'Продолжить привязку'}).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await page.getByLabel('Ссылка привязки').fill('https://workspace.test/'+fixture.fragment);
  await page.getByRole('button',{name:'Продолжить привязку'}).click();
 }
 await page.getByRole('button',{name:'Привязать',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Ключи проверены и сохранены');
 const persisted=await page.evaluate(async workspace=>{
   // @ts-expect-error Vite test module
   const vault=await import('/src/features/encryption/vault.ts');
   const device=await vault.loadDevice('10',workspace);
   return {revision:device?.bundle?.revision,exportable:device?.signing.privateKey.extractable,hash:location.hash};
 },fixture.invite.workspace);
 expect(persisted).toEqual({revision:1,exportable:false,hash:''});
 expect(traffic.join('\n')).not.toContain(fixture.invite.secret);
 expect(traffic.join('\n')).not.toContain(fixture.fragment);
 await page.reload();
 const restored=await page.evaluate(async workspace=>{
  // @ts-expect-error Vite test module
  const v=await import('/src/features/encryption/vault.ts');
  return (await v.loadDevice('10',workspace))?.bundle?.revision;
 },fixture.invite.workspace);
 expect(restored).toBe(1);
});
