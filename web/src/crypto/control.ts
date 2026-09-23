/** Bounded waiting; callers persist the signed envelope before sending it. */
import {request} from '../api/transport';
import {readVerifiedRecords} from './records';
import type {Device} from './vault';
import type {Envelope} from './envelope';

export async function waitForControlResult(device:Device,envelope:Envelope,assertCurrent:()=>void,onProgress?:(seconds:number)=>void){
 const started=Date.now(),deadline=started+120000;
 const timer=setInterval(()=>onProgress?.(Math.floor((Date.now()-started)/1000)),1000);
 try{
  onProgress?.(0);assertCurrent();
  await request('/web/e2ee/send',{envelope});assertCurrent();
  while(Date.now()<deadline){
   const replies=await readVerifiedRecords(device,envelope.context[1],'control-result');assertCurrent();
   const reply=replies.get(envelope.context[3])?.value as Record<string,unknown>|undefined;
   if(reply)return reply;
   await new Promise(resolve=>setTimeout(resolve,2000));assertCurrent();
  }
  throw new Error('Локальный обработчик пока не ответил. Повторите попытку, чтобы продолжить ожидание.');
 }finally{clearInterval(timer);}
}
