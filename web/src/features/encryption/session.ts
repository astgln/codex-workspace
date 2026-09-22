import {assembleResponse} from './response';
import type {WorkspaceState,HistoryPage,Message} from '../../shared/api/types';
import {loadDevice,type Device} from './vault';
import {refreshDeviceKeys,readVerifiedRecords} from './records';
import {decode} from './envelope';
import type {AttachmentManifest} from './attachments';

import {encryptedControl} from './devices';

type ModeState=WorkspaceState&{encryption?:{v:number;workspace:string};encryption_locked?:boolean};
type Session={state:ModeState;account:string;workspace:string;device:Device|null};
let session:Session|null=null;
export const manifests=new Map<string,AttachmentManifest>();
export const pending=new Map<string,Message>();
export const downloads=new Map<string,{scope:string;manifest:AttachmentManifest;signer:string}>();
let generation=0;
async function db(){return new Promise<IDBDatabase>((resolve,reject)=>{
 const r=indexedDB.open('workspace-encrypted-client-v1',1);
 r.onupgradeneeded=()=>{r.result.createObjectStore('pins');r.result.createObjectStore('outbox');};
 r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(new Error('Хранилище E2EE недоступно.'));
});}
export async function stored<T>(table:string,key:string,value?:T):Promise<T|undefined>{
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
export function current(){if(!session?.device?.bundle)throw new Error('Привяжите это устройство для доступа к переписке.');return session as Session&{device:Device};}
export function check(s:Session){if(session!==s)throw new Error('Сессия изменилась.');}

export async function initializeEncryption(state:ModeState):Promise<ModeState>{
 const version=++generation;
 const account=String(state.user.id);
 if(session&&(session.account!==account||session.workspace!==state.encryption?.workspace)){session=null;manifests.clear();pending.clear();downloads.clear();}
 const pin=await stored<string>('pins',account);
 if(version!==generation)throw new Error('Сессия изменилась.');
 if(!state.encryption){
  if(pin)throw new Error('Сервер предлагает отключить E2EE. Соединение остановлено.');
  clearEncryptedSession();throw new Error('Сервер не настроен для E2EE.');
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
 const ownCatalog=await readVerifiedRecords(s.device,'device:'+s.device.deviceStamp,'catalog');check(s);
 const access=ownCatalog.get('access')?.value as {user:WorkspaceState['user'];members:WorkspaceState['members']}|undefined;
 if(!access||String(access.user?.id)!==s.account)throw new Error('Ожидаем подтверждённые права устройства с ноутбука.');
 const catalog=access.user.role==='owner'?await readVerifiedRecords(s.device,'workspace','catalog'):ownCatalog;check(s);
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
   const payload=await assembleResponse(entry.value,responses) as {attachment_signer:string;request:{thread:string;text:string;created:number;sender:number;snapshot:string;attachments:AttachmentManifest[]};result:{id:number;status:string;events:Message['events']}};
   if(!payload?.request||payload.request.thread!==thread.id||!payload.result)throw new Error('Некорректный зашифрованный ответ.');
   const dispatch=responses.get('dispatch:'+record)?.value as {reason?:string;observed_at?:number}|undefined;
   const waiting=payload.result.status==='queued'&&dispatch?.observed_at&&Date.now()/1000-dispatch.observed_at<120
     ? dispatch.reason:undefined;
   const status=waiting==='desktop_writer_lock'?'waiting_for_task':waiting==='task_settings_unavailable'?'waiting_for_settings':payload.result.status;
   messages.push({id:payload.result.id,sender:payload.request.sender,thread:thread.id,text:payload.request.text,created:payload.request.created,
     expires:0,status:['queued','awaiting_approval','rejected'].includes(payload.result.status)?payload.result.status:'delivered',snapshot:payload.request.snapshot,result_status:status,events:payload.result.events,attachments:payload.request.attachments});
   for(const manifest of payload.request.attachments){
    const previous=downloads.get(manifest.id);
    if(previous&&JSON.stringify(previous)!==JSON.stringify({scope:thread.id,manifest,signer:payload.attachment_signer}))throw new Error('Идентификатор вложения повторён.');
    downloads.set(manifest.id,{scope:thread.id,manifest,signer:payload.attachment_signer});
   }
   pending.delete(record);
  }
 }
 const quota=catalog.get('quota')?.value as WorkspaceState['weekly_quota'];
 return {...s.state,user:access.user,members:access.members,projects,threads,messages:[...messages,...pending.values()],weekly_quota:quota,catalog_updated:index.updated_at,collector_seen:index.updated_at,encryption_locked:false};
}

export async function encryptedHistory(thread:string,_before?:string):Promise<HistoryPage>{
 const s=current();const records=await readVerifiedRecords(s.device,thread,'history');check(s);
 const messages=[...records.entries()].filter(([key])=>key!=='checkpoint').map(([,value])=>value.value) as HistoryPage['messages'];
 const checkpoint=records.get('checkpoint')?.value as {synced_at:number}|undefined;
 return {messages:messages.sort((a,b)=>a.position.localeCompare(b.position)),before:null,synced_at:checkpoint?.synced_at??null,loading_older:false,pending:!checkpoint};
}

export async function encryptedDiagnostics(){
 const s=current();s.device.bundle=await refreshDeviceKeys(s.device);check(s);
 const records=await readVerifiedRecords(s.device,'workspace','catalog');check(s);
 const status=records.get('worker')?.value as {worker:{status:string;observed_at:number;waiting:Record<string,number>;unresolved:number};queue:Record<string,number>;completed:number}|undefined;
 const seen=status?.worker?.observed_at??null;
 return {collector_seen:seen,collector_recent:seen!==null&&Date.now()/1000-seen<600,
  history_synced:null,worker:status?.worker,queue:status?.queue??{queued:0},completed:status?.completed??0,notifications:null};
}
