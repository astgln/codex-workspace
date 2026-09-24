/** UI-only test double injected by Playwright; production never imports this. */
import {ApiError} from '../../src/shared/api/transport';
import type {Attachment} from '../../src/shared/api/types';
async function request<T>(path:string,body?:unknown):Promise<T>{
 const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'test-csrf'},body:body===undefined?undefined:JSON.stringify(body)});
 if(!response.ok)throw new ApiError(response.status,response.status===401?'Сессия истекла. Войдите снова.':'Сервис временно недоступен. Попробуйте снова.');
 return response.json();
}
export const initializeEncryption=async(state:unknown)=>state;
export const clearEncryptedSession=()=>{};
export const encryptedActive=()=>false;
export const encryptedState=()=>request('/web/state',{});
export const encryptedSend=(thread:string,text:string,request_id:string,attachments:string[])=>request('/web/messages',{thread,text,request_id,attachments});
export const encryptedHistory=(thread:string,before?:string)=>request('/web/history',{thread,...(before?{before}:{})});
export const encryptedDiagnostics=()=>request('/web/diagnostics',{});
export const createDeviceInvitation=()=>{throw new Error('Not part of UI fixture');};
export const encryptedDownload=()=>{throw new Error('Not part of UI fixture');};
async function sha256(bytes:Uint8Array){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes as BufferSource))).map(b=>b.toString(16).padStart(2,'0')).join('');}
export async function encryptedUpload(thread:string,file:File,ensureActive:()=>void=()=>{}):Promise<Attachment>{
  if(!file.size||file.size>5*1024*1024)throw new Error('Размер файла должен быть от 1 байта до 5 МБ.');
  const bytes=new Uint8Array(await file.arrayBuffer());
  const digest=await sha256(bytes);
  ensureActive();
  const upload=await request<Attachment&{chunk_size:number}>('/web/uploads/start',{thread,name:file.name,size:file.size,sha256:digest,request_id:crypto.randomUUID()});
  for(let offset=0,index=0;offset<bytes.length;offset+=upload.chunk_size,index++){
    ensureActive();
    const part=bytes.slice(offset,offset+upload.chunk_size);
    const data=btoa(String.fromCharCode(...part));
    await request('/web/uploads/chunk',{id:upload.id,index,data});
  }
  ensureActive();
  return request<Attachment>('/web/uploads/finish',{id:upload.id});
}
