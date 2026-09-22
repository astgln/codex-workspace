import {test,expect} from '@playwright/test';

test('encrypted session restores catalog/history, sends only ciphertext and rejects downgrade',async({page})=>{
 const transmitted:string[]=[];
 let records:Record<string,unknown[]>={};
 const controls:unknown[]=[];
 let rejectControl=true;
 await page.route('https://workspace.test/**',async r=>{
  const u=new URL(r.request().url());
  if(u.pathname==='/auth/session')return r.fulfill({status:401,json:{}});
  if(u.pathname.startsWith('/web/')){
   transmitted.push(u.pathname+' '+(r.request().postData()||''));
   const body=r.request().postDataJSON();
   if(u.pathname==='/web/e2ee/read'){
    const rows=records[body.scope+':'+body.kind]||[];
    return r.fulfill({json:{records:rows,after:rows.length,more:false}});
   }
   if(u.pathname==='/web/e2ee/send'&&body.envelope.context[2]==='control'){
    controls.push(body.envelope);
    if(rejectControl)return r.fulfill({status:503,json:{}});
   }
   if(u.pathname==='/web/e2ee/send')return r.fulfill({json:{sequence:1,duplicate:false}});
   return r.fulfill({status:500,json:{}});
  }
  return r.fulfill({response:await r.fetch({url:'http://127.0.0.1:5173'+u.pathname+u.search})});
 });
 await page.goto('https://workspace.test/');
 const fixture=await page.evaluate(async()=>{
  // @ts-expect-error Vite module
  const c=await import('/src/features/encryption/envelope.ts');
  // @ts-expect-error Vite module
  const v=await import('/src/features/encryption/vault.ts');
  const workspace=c.encode(crypto.getRandomValues(new Uint8Array(32)));
  const root=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
  const authority=c.encode(new Uint8Array(await crypto.subtle.exportKey('spki',root.publicKey)));
  const device=await v.getOrCreateDevice('10',workspace);
  const keys=[];
  for(const scope of ['workspace','task','device:'+device.deviceStamp]){
   const raw=crypto.getRandomValues(new Uint8Array(32));keys.push({scope,epoch:1,key:c.encode(raw),id:await c.keyId(raw)});
  }
  await v.installBundle('10',{v:1,workspace,origin:location.origin,device:device.deviceStamp,authority,revision:1,keys},
   {workspace,origin:location.origin,authority});
  const records:Record<string,unknown[]>={};
  const add=async(scope:string,kind:string,record:string,payload:unknown)=>{
   const k=keys.find(k=>k.scope===scope)!;const list=records[scope+':'+kind]??=[];
   list.push({sequence:list.length+1,envelope:await c.seal(c.decode(k.key,32),root,[workspace,scope,kind,record,1],new TextEncoder().encode(JSON.stringify(payload)))});
  };
  await add('device:'+device.deviceStamp,'catalog','access',{user:{id:10,role:'owner',requires_approval:false},members:[]});
  await add('workspace','catalog','index',{projects:['project'],threads:['task'],updated_at:1000});
  await add('workspace','catalog','project:abc',{id:'project',title:'private project'});
  await add('workspace','catalog','task:task',{id:'task',title:'private task',status:'idle',project_id:'project'});
  await add('task','history','message',{id:'message',position:'001',role:'assistant',text:'private old answer',created:900});
  await add('task','history','checkpoint',{synced_at:1000});
  await add('task','response','request',{request:{sender:10,snapshot:'snapshot',thread:'task',text:'private old request',created:999,attachments:[]},result:{id:-1,status:'completed',events:[]}});
  await add('task','response','dispatch:request',{reason:'desktop_writer_lock',observed_at:Math.floor(Date.now()/1000)});
  await add('task','response','waiting',{request:{thread:'task',sender:10,text:'waiting request',created:999,attachments:[]},result:{id:-2,status:'queued',events:[]}});
  await add('task','response','dispatch:waiting',{reason:'desktop_writer_lock',observed_at:Math.floor(Date.now()/1000)});
  await add('task','push','preview',{thread:'task',title:'private notification',body:'private push text',created:Math.floor(Date.now()/1000)});
  (window as any).invitationReply=async(record:string)=>{
   const scope='device:'+device.deviceStamp;
   await add(scope,'control-result',record,{invitation:{workspace,authority,expires:Math.floor(Date.now()/1000)+600,secret:'fixture-only'}});
   return {scope,rows:records[scope+':control-result']};
  };
  return {records,state:{user:{id:10},threads:[],messages:[],collector_seen:null,catalog_updated:null,encryption:{v:1,workspace}}};
 });
 records=fixture.records;
 const result=await page.evaluate(async state=>{
  // @ts-expect-error Vite module
  const client=await import('/src/features/encryption/client.ts');
  const loaded=await client.initializeEncryption(state);
  const history=await client.encryptedHistory('task');
  const message=await client.encryptedSend('task','private new request','test-request-id',[]);
  return {title:loaded.projects[0].title,old:loaded.messages[0].text,history:history.messages[0].text,synced:history.synced_at,status:message.status,resultStatus:loaded.messages[0].result_status,waitingStatus:loaded.messages[1].result_status};
 },fixture.state);
 expect(result).toEqual({title:'private project',old:'private old request',history:'private old answer',synced:1000,status:'queued',resultStatus:'completed',waitingStatus:'waiting_for_task'});
 expect(transmitted.join('\n')).not.toContain('private');
 // A lost response must retry the exact encrypted invitation, not create another one.
 for(let attempt=0;attempt<2;attempt++){
  expect(await page.evaluate(async()=>{
   // @ts-expect-error Vite module
   const client=await import('/src/features/encryption/client.ts');
   try{await client.createDeviceInvitation();return false;}catch{return true;}
  })).toBe(true);
 }
 expect(controls).toHaveLength(2);expect(controls[1]).toEqual(controls[0]);
 const control=controls[0] as {context:string[]};
 const reply=await page.evaluate(record=>(window as any).invitationReply(record),control.context[3]);
 records[reply.scope+':control-result']=reply.rows;rejectControl=false;
 const invitation=await page.evaluate(async()=>{
  // @ts-expect-error Vite module
  const client=await import('/src/features/encryption/client.ts');
  return client.createDeviceInvitation();
 });
 expect(invitation.link).toContain('/#pair=');
 expect(controls[2]).toEqual(controls[0]);
 expect(transmitted.join('\n')).not.toContain('fixture-only');
 const downgrade=await page.evaluate(async()=>{
  // @ts-expect-error Vite module
  const client=await import('/src/features/encryption/client.ts');
  try{await client.initializeEncryption({user:{id:10},threads:[],messages:[]});return false;}catch{return true;}
 });
 expect(downgrade).toBe(true);
 const preview=await page.evaluate(async envelope=>{
  // @ts-expect-error Vite module
  const p=await import('/src/features/encryption/push.ts');
  const valid=await p.encryptedPush(envelope);
  const changed=structuredClone(envelope);changed.context[1]='other-task';
  const invalid=await p.encryptedPush(changed);return {valid,invalid};
 },(fixture.records['task:push'][0] as {envelope:unknown}).envelope);
 expect(preview.valid.title).toBe('private notification');
 expect(preview.valid.body).toBe('private push text');
 expect(preview.invalid.body).toBe('Новое зашифрованное сообщение');
});

test('fresh browser refuses an unencrypted workspace and content endpoints before enrollment',async({page})=>{
 await page.goto('/');
 const result=await page.evaluate(async()=>{
  // @ts-expect-error Vite test module
  const client=await import('/src/features/encryption/client.ts');
  // @ts-expect-error Vite test module
  const transport=await import('/src/shared/api/transport.ts');
  const failures:string[]=[];
  try{await client.initializeEncryption({user:{id:98765},threads:[],messages:[]});}catch(error){failures.push(String(error));}
  for(const path of ['/web/state','/web/messages','/web/history','/web/uploads/start','/web/diagnostics','/web/push/subscribe']){
   try{await transport.request(path,{});}catch(error){failures.push(String(error));}
  }
  return failures;
 });
 expect(result).toHaveLength(7);
 expect(result[0]).toContain('Сервер не настроен для E2EE');
 expect(result.slice(1).every(value=>value.includes('Передача открытого текста отключена'))).toBe(true);
});
