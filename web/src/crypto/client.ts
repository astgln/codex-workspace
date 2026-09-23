import {waitForControlResult} from './control';
/** Encrypted application session. No plaintext transport fallback after a mode pin. */
import type {WorkspaceState,HistoryPage,Message} from '../api/types';
import {request,requireEncryptedTransport} from '../api/transport';
import {loadDevice,type Device} from './vault';
import {refreshDeviceKeys,readVerifiedRecords} from './records';
import {decode,encode,seal,openEnvelope} from './envelope';
import {decodeObject} from './bundle';
import {encryptAttachment,uploadEncryptedAttachment,downloadEncryptedAttachment,hash,type AttachmentManifest} from './attachments';

type ModeState=WorkspaceState&{encryption?:{v:number;workspace:string};encryption_locked?:boolean};
type Session={state:ModeState;account:string;workspace:string;device:Device|null};
let session:Session|null=null;
const manifests=new Map<string,AttachmentManifest>();
const pending=new Map<string,Message>();
const downloads=new Map<string,{scope:string;manifest:AttachmentManifest;signer:string}>();
let generation=0;
async function db(){return new Promise<IDBDatabase>((resolve,reject)=>{
 const r=indexedDB.open('workspace-encrypted-client-v1',1);
 r.onupgradeneeded=()=>{r.result.createObjectStore('pins');r.result.createObjectStore('outbox');};
 r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(new Error('Хранилище E2EE недоступно.'));
});}
async function stored<T>(table:string,key:string,value?:T):Promise<T|undefined>{
 const database=await db();
 try{return await new Promise((resolve,reject)=>{
  const tx=database.transaction(table,value===undefined?'readonly':'readwrite');
  const req=value===undefined?tx.objectStore(table).get(key):tx.objectStore(table).put(value,key);
  let result:T|undefined;req.onsuccess=()=>{result=value===undefined?req.result:value;};
  tx.oncomplete=()=>resolve(result);tx.onerror=tx.onabort=()=>reject(new Error('Не удалось сохранить состояние E2EE.'));
 });}finally{database.close();}
}
export const encryptedActive=()=>session!==null;
export function clearEncryptedSession(){generation++;session=null;manifests.clear();pending.clear();downloads.clear();}
function current(){if(!session?.device?.bundle)throw new Error('Привяжите это устройство для доступа к переписке.');return session as Session&{device:Device};}
function check(s:Session){if(session!==s)throw new Error('Сессия изменилась.');}

export async function initializeEncryption(state:ModeState):Promise<ModeState>{
 const version=++generation;
 const account=String(state.user.id);
 if(session&&(session.account!==account||session.workspace!==state.encryption?.workspace)){session=null;manifests.clear();pending.clear();downloads.clear();}
 const pin=await stored<string>('pins',account);
 if(version!==generation)throw new Error('Сессия изменилась.');
 if(pin||state.encryption)requireEncryptedTransport();
 if(!state.encryption){
  if(pin)throw new Error('Сервер предлагает отключить E2EE. Соединение остановлено.');
  clearEncryptedSession();return state;
 }
 const mode=state.encryption;
 if(mode.v!==1||typeof mode.workspace!=='string')throw new Error('Неподдерживаемый режим E2EE.');
 decode(mode.workspace,32,32);
 if(pin&&pin!==mode.workspace)throw new Error('Идентификатор зашифрованного пространства изменён.');
 const device=await loadDevice(account,mode.workspace);
 if(version!==generation)throw new Error('Сессия изменилась.');
 session={state,account,workspace:mode.workspace,device};
 if(!device?.bundle)return {...state,encryption_locked:true};
 if(device.bundle.origin!==location.origin)throw new Error('Ключи выданы другому сайту.');
 await stored('pins',account,mode.workspace);
 return encryptedState();
}

export async function encryptedState():Promise<ModeState>{
 if(!session)throw new Error('Нет зашифрованной сессии.');
 const initial=session;
 if(!initial.device?.bundle){initial.device=await loadDevice(initial.account,initial.workspace);check(initial);}
 if(!initial.device?.bundle)return {...initial.state,encryption_locked:true};
 if(initial.device.bundle.origin!==location.origin)throw new Error('Ключи выданы другому сайту.');
 await stored('pins',initial.account,initial.workspace);check(initial);
 const s=current();s.device.bundle=await refreshDeviceKeys(s.device);check(s);
 const catalog=await readVerifiedRecords(s.device,'workspace','catalog');check(s);
 const index=catalog.get('index')?.value as {projects:string[];threads:string[];updated_at:number}|undefined;
 if(!index||!Array.isArray(index.projects)||!Array.isArray(index.threads))throw new Error('Ожидаем зашифрованный каталог с ноутбука.');
 const all=[...catalog.values()].map(x=>x.value) as Record<string,unknown>[];
 const projects=index.projects.map(id=>all.find(p=>p.id===id&&typeof p.title==='string')).filter(Boolean) as {id:string;title:string}[];
 const threads=index.threads.map(id=>catalog.get('task:'+id)?.value).filter(Boolean) as WorkspaceState['threads'];
 const messages:Message[]=[];
 for(const thread of threads){
  const responses=await readVerifiedRecords(s.device,thread.id,'response');check(s);
  for(const [record,entry] of responses){
   if(record.startsWith('part:')||record.startsWith('dispatch:'))continue;
   const payload=await assembleResponse(entry.value,responses) as {attachment_signer:string;request:{thread:string;text:string;created:number;attachments:AttachmentManifest[]};result:{id:number;status:string;events:Message['events']}};
   if(!payload?.request||payload.request.thread!==thread.id||!payload.result)throw new Error('Некорректный зашифрованный ответ.');
   const dispatch=responses.get('dispatch:'+record)?.value as {reason?:string;observed_at?:number}|undefined;
   const waiting=payload.result.status==='queued'&&dispatch?.observed_at&&Date.now()/1000-dispatch.observed_at<120
     ? dispatch.reason:undefined;
   const status=waiting==='desktop_writer_lock'?'waiting_for_task':waiting==='task_settings_unavailable'?'waiting_for_settings':payload.result.status;
   messages.push({id:payload.result.id,sender:Number(s.account),thread:thread.id,text:payload.request.text,created:payload.request.created,
     expires:0,status:payload.result.status==='queued'?'queued':'delivered',snapshot:record,result_status:status,events:payload.result.events,attachments:payload.request.attachments});
   for(const manifest of payload.request.attachments){
    const previous=downloads.get(manifest.id);
    if(previous&&JSON.stringify(previous)!==JSON.stringify({scope:thread.id,manifest,signer:payload.attachment_signer}))throw new Error('Идентификатор вложения повторён.');
    downloads.set(manifest.id,{scope:thread.id,manifest,signer:payload.attachment_signer});
   }
   pending.delete(record);
  }
 }
 const quota=catalog.get('quota')?.value as WorkspaceState['weekly_quota'];
 return {...s.state,projects,threads,messages:[...messages,...pending.values()],weekly_quota:quota,catalog_updated:index.updated_at,collector_seen:index.updated_at,encryption_locked:false};
}

export async function encryptedHistory(thread:string):Promise<HistoryPage>{
 const s=current();const records=await readVerifiedRecords(s.device,thread,'history');check(s);
 const messages=[...records.entries()].filter(([key])=>key!=='checkpoint').map(([,value])=>value.value) as HistoryPage['messages'];
 const checkpoint=records.get('checkpoint')?.value as {synced_at:number}|undefined;
 return {messages:messages.sort((a,b)=>a.position.localeCompare(b.position)),before:null,synced_at:checkpoint?.synced_at??null,loading_older:false,pending:!checkpoint};
}

export async function encryptedUpload(thread:string,file:File,ensureActive:()=>void){
 const s=current();const key=s.device.bundle!.keys.filter(k=>k.scope===thread).sort((a,b)=>b.epoch-a.epoch)[0];
 if(!key)throw new Error('Нет ключа задачи.');
 const prepared=await encryptAttachment(file,s.workspace,key,s.device.signing);check(s);ensureActive();
 const manifest=await uploadEncryptedAttachment(s.workspace,thread,prepared,()=>{check(s);ensureActive();});
 check(s);ensureActive();manifests.set(manifest.id,manifest);return manifest;
}

export async function encryptedSend(thread:string,text:string,id:string,files:string[]):Promise<Message>{
 const s=current();
 const storageId=JSON.stringify([s.account,s.workspace,id]);
 let entry=await stored<{envelope:Awaited<ReturnType<typeof seal>>}>('outbox',storageId);check(s);
 const attachments=files.map(id=>{const m=manifests.get(id);if(!m)throw new Error('Вложение недоступно в этой сессии.');return m;});
 if(!entry){
  const key=s.device.bundle!.keys.filter(k=>k.scope===thread).sort((a,b)=>b.epoch-a.epoch)[0];
  if(!key)throw new Error('Нет ключа задачи.');
  const record=encode(crypto.getRandomValues(new Uint8Array(32))),now=Math.floor(Date.now()/1000);
  const intent={v:1,workspace:s.workspace,thread,request_id:record,issued_at:now,expires_at:now+86400,text,attachments};
  entry={envelope:await seal(decode(key.key,32,32),s.device.signing,[s.workspace,thread,'request',record,1],new TextEncoder().encode(JSON.stringify(intent)))};
  check(s);await stored('outbox',storageId,entry);
 }
 const e=entry.envelope,key=s.device.bundle!.keys.find(k=>k.id===e.key_id&&k.scope===thread);
 if(!key)throw new Error('Ключ запроса больше не доступен.');
 const intent=decodeObject(await openEnvelope(decode(key.key,32,32),s.device.signing.publicKey,[s.workspace,thread,'request',e.context[3],1],e)) as {text:string;attachments:AttachmentManifest[];issued_at:number;expires_at:number};
 if(intent.text!==text||JSON.stringify(intent.attachments)!==JSON.stringify(attachments)||intent.expires_at<=Date.now()/1000)throw new Error('Повтор запроса изменён или просрочен.');
 check(s);await request('/web/e2ee/send',entry);check(s);
 const message:Message={id:-Date.now(),sender:Number(s.account),thread,text,created:intent.issued_at,expires:intent.expires_at,status:'queued',snapshot:e.context[3],attachments};
 pending.set(e.context[3],message);return message;
}

export async function encryptedDownload(file:{id:string;name:string;size:number;sha256:string}){
 const s=current(),entry=downloads.get(file.id);
 if(!entry||entry.manifest.name!==file.name||entry.manifest.size!==file.size||entry.manifest.sha256!==file.sha256)throw new Error('Нет проверенного описания вложения. Обновите задачу.');
 return downloadEncryptedAttachment(s.workspace,entry.scope,entry.manifest,entry.signer,s.device.bundle!,()=>check(s));
}

async function assembleResponse(value:unknown,records:Map<string,{revision:number;value:unknown}>):Promise<unknown>{
 const manifest=value as {payload_type?:string;parts:string[];size:number;sha256:string};
 if(manifest?.payload_type!=='parts-v1')return value;
 if(!Array.isArray(manifest.parts)||manifest.parts.length>86||!Number.isSafeInteger(manifest.size)||manifest.size<1||manifest.size>4*1024*1024)throw new Error('Некорректный размер зашифрованного ответа.');
 const bytes=new Uint8Array(manifest.size);let offset=0;
 for(const id of manifest.parts){
  const part=records.get(id)?.value as {data:string}|undefined;
  if(!part||!/^part:[a-f0-9]{64}$/.test(id))throw new Error('Ожидаем все части зашифрованного ответа.');
  const chunk=decode(part.data,48*1024);
  if(!chunk.length||id!=='part:'+await hash(chunk)||offset+chunk.length>bytes.length)throw new Error('Часть ответа изменена.');
  bytes.set(chunk,offset);offset+=chunk.length;
 }
 if(offset!==bytes.length||await hash(bytes)!==manifest.sha256)throw new Error('Ответ загружен не полностью.');
 return decodeObject(bytes);
}

export async function createDeviceInvitation(onProgress?:(seconds:number)=>void){
 const s=current(),scope='device:'+s.device.deviceStamp;
 const key=s.device.bundle!.keys.filter(k=>k.scope===scope).sort((a,b)=>b.epoch-a.epoch)[0];
 if(!key)throw new Error('Нет ключа управления устройством.');
 const storageId=JSON.stringify(['pair-device',s.account,s.workspace,s.device.deviceStamp]);
 let entry=await stored<{envelope:Awaited<ReturnType<typeof seal>>;expires:number}>('outbox',storageId);check(s);
 const now=Math.floor(Date.now()/1000);
 if(!entry||entry.expires<=now){
  const record=encode(crypto.getRandomValues(new Uint8Array(32)));
  entry={expires:now+600,envelope:await seal(decode(key.key,32,32),s.device.signing,[s.workspace,scope,'control',record,1],
   new TextEncoder().encode(JSON.stringify({action:'pair-device',issued_at:now,expires_at:now+600})))};
  check(s);await stored('outbox',storageId,entry);check(s);
 }
 const reply=await waitForControlResult(s.device,entry.envelope,()=>check(s),onProgress);
 const invitation=reply.invitation as {workspace:string;authority:string;expires:number}|undefined;
 if(!invitation||invitation.workspace!==s.workspace||invitation.authority!==s.device.bundle!.authority||invitation.expires<=Date.now()/1000)throw new Error('Приглашение истекло. Создайте новую ссылку.');
 await stored('outbox',storageId,{...entry,expires:0});check(s);
 return {link:location.origin+'/#pair='+encode(new TextEncoder().encode(JSON.stringify(invitation))),expires:invitation.expires};
}

export async function encryptedDiagnostics(){
 const s=current();s.device.bundle=await refreshDeviceKeys(s.device);check(s);
 const records=await readVerifiedRecords(s.device,'workspace','catalog');check(s);
 const status=records.get('worker')?.value as {worker:{status:string;observed_at:number;waiting:Record<string,number>;unresolved:number};queue:Record<string,number>;completed:number}|undefined;
 const seen=status?.worker?.observed_at??null;
 return {collector_seen:seen,collector_recent:seen!==null&&Date.now()/1000-seen<600,
  history_synced:null,worker:status?.worker,queue:status?.queue??{queued:0},completed:status?.completed??0,notifications:null};
}
