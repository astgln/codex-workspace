import type {Message} from '../../shared/api/types';
import {request} from '../../shared/api/transport';
import {decode,encode,seal,openEnvelope} from './envelope';
import {decodeObject} from './bundle';
import {encryptAttachment,uploadEncryptedAttachment,downloadEncryptedAttachment,type AttachmentManifest} from './attachments';
import {current,check,stored,manifests,pending,downloads} from './session';

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
