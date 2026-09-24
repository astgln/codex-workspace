/** Push previews are opened only with endpoint-pinned authority and scope keys. */
import {loadDevice,type Device} from './vault';
import {importAuthority,decodeObject} from './bundle';
import {decode,openEnvelope,type Envelope} from './envelope';
const neutral={title:'Codex Workspace',body:'Новое зашифрованное сообщение',url:'/',tag:'encrypted-workspace'};
async function devices():Promise<Device[]>{
 return new Promise((resolve,reject)=>{
  const r=indexedDB.open('workspace-endpoint-keys-v1',1);
  r.onupgradeneeded=()=>r.result.createObjectStore('devices',{keyPath:'identity'});
  r.onerror=()=>reject(new Error('Keys unavailable'));
  r.onsuccess=()=>{
   const db=r.result,tx=db.transaction('devices','readonly'),get=tx.objectStore('devices').getAll();
   let result:Device[]=[];get.onsuccess=()=>{result=get.result;};
   tx.oncomplete=()=>{db.close();resolve(result);};tx.onabort=tx.onerror=()=>{db.close();reject(new Error('Keys unavailable'));};
  };
 });
}
export async function encryptedPush(envelope:Envelope){
 try{
  const context=envelope?.context;
  if(!Array.isArray(context)||context.length!==5||context[2]!=='push')return neutral;
  for(const candidate of await devices()){
   if(candidate.workspace!==context[0]||!candidate.bundle||candidate.bundle.origin!==location.origin)continue;
   const key=candidate.bundle.keys.find(k=>k.scope===context[1]&&k.id===envelope.key_id);if(!key)continue;
   const decoded=decodeObject(await openEnvelope(decode(key.key,32,32),await importAuthority(candidate.bundle.authority),
    [context[0],context[1],'push',context[3],context[4]],envelope)) as {title:string;body:string;created:number;thread:string};
   if(decoded.thread!==context[1]||typeof decoded.title!=='string'||typeof decoded.body!=='string'||
     !Number.isSafeInteger(decoded.created)||decoded.created>Date.now()/1000+60||decoded.created<Date.now()/1000-86400)return neutral;
   const fresh=await loadDevice(candidate.account,candidate.workspace);
   if(!fresh?.bundle||fresh.deviceStamp!==candidate.deviceStamp||!fresh.bundle.keys.some(k=>k.id===key.id))return neutral;
   return {title:Array.from(decoded.title).slice(0,120).join('')||neutral.title,body:Array.from(decoded.body).slice(0,520).join('')||neutral.body,
    url:/^[a-zA-Z0-9-]+$/.test(decoded.thread)?'/#thread='+decoded.thread:'/',tag:'encrypted:'+decoded.thread};
  }
 }catch{/* Untrusted push failures never expose payloads in diagnostics. */}
 return neutral;
}
export async function hasEncryptedDevices(){try{return (await devices()).some(d=>Boolean(d.bundle));}catch{return true;}}
