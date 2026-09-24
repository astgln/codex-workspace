import {waitForControlResult} from './control';
import {decode,encode,seal} from './envelope';
import {current,check,stored} from './session';

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

