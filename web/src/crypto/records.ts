/** Read only root-signed records; relay metadata never establishes trust. */
import {request} from '../api/transport';
import {decodeObject, importAuthority} from './bundle';
import {decode, openEnvelope, type Envelope} from './envelope';
import {installBundle, type Device} from './vault';

type Stored = {id:string; revision:number; serialized:string; envelope:Envelope};
const database='workspace-encrypted-records-v1';
function openDB():Promise<IDBDatabase>{
 return new Promise((resolve,reject)=>{
  const r=indexedDB.open(database,1);
  r.onupgradeneeded=()=>r.result.createObjectStore('records',{keyPath:'id'});
  r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(new Error('Хранилище зашифрованных записей недоступно.'));
 });
}
async function persist(id:string,envelope:Envelope){
 const db=await openDB();
 try {
  await new Promise<void>((resolve,reject)=>{
   const tx=db.transaction('records','readwrite'),store=tx.objectStore('records');
   const serialized=JSON.stringify(envelope),revision=envelope.context[4];
   const read=store.get(id);
   read.onsuccess=()=>{
    const old=read.result as Stored|undefined;
    if(old&&(old.revision>revision||old.revision===revision&&old.serialized!==serialized)){tx.abort();return;}
    store.put({id,revision,serialized,envelope});
   };
   tx.oncomplete=()=>resolve();tx.onerror=tx.onabort=()=>reject(new Error('Получена устаревшая или изменённая запись.'));
  });
 }finally{db.close();}
}

export async function readVerifiedRecords(device:Device,scope:string,kind:'history'|'catalog'|'response'|'push'|'key-wrap'|'control-result') {
 const bundle=device.bundle;
 if(!bundle||bundle.origin!==location.origin)throw new Error('Устройство не привязано к этому сайту.');
 const authority=await importAuthority(bundle.authority);
 let after=0;
 const values=new Map<string,{revision:number;value:unknown}>();
 for(let page=0;page<200;page++){
  const reply=await request<{records:{sequence:number;envelope:Envelope}[];after:number;more:boolean}>('/web/e2ee/read',
   {workspace:device.workspace,scope,kind,after});
  if(!reply||!Array.isArray(reply.records)||reply.records.length>50||typeof reply.more!=='boolean')throw new Error('Некорректный ответ шифрованного канала.');
  for(const entry of reply.records){
   const envelope=entry?.envelope,context=envelope?.context;
   if(!Number.isSafeInteger(entry.sequence)||entry.sequence<=after||!Array.isArray(context)||context.length!==5||
     context[0]!==device.workspace||context[1]!==scope||context[2]!==kind||typeof context[3]!=='string')throw new Error('Контекст шифрованной записи изменён.');
   const key=bundle.keys.find(k=>k.scope===scope&&k.id===envelope.key_id);
   if(!key)throw new Error('Для записи нет ключа. Обновите ключи устройства.');
   const raw=await openEnvelope(decode(key.key,32,32),authority,[device.workspace,scope,kind,context[3],context[4]],envelope);
   const value=decodeObject(raw);raw.fill(0);
   await persist(JSON.stringify([device.account,device.workspace,scope,kind,context[3]]),envelope);
   if(values.has(context[3]))throw new Error('Сервер повторил запись в одной выборке.');
   values.set(context[3],{revision:context[4],value});after=entry.sequence;
  }
  if(reply.after!==after||reply.more&&reply.records.length===0)throw new Error('Некорректный курсор шифрованной истории.');
  if(!reply.more)return values;
 }
 throw new Error('Превышен размер шифрованной выборки.');
}

export async function refreshDeviceKeys(device:Device){
 if(!device.bundle)throw new Error('Устройство не привязано.');
 const records=await readVerifiedRecords(device,'device:'+device.deviceStamp,'key-wrap');
 const update=records.get('bundle');
 if(!update)return device.bundle;
 return installBundle(device.account,update.value,{workspace:device.workspace,origin:location.origin,authority:device.bundle.authority});
}
