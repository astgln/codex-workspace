import { request } from './transport';
import type { Attachment } from './types';
async function sha256(bytes:Uint8Array){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes as BufferSource))).map(b=>b.toString(16).padStart(2,'0')).join('');}
export async function uploadFile(thread:string,file:File,onProgress:(percent:number)=>void,ensureActive:()=>void=()=>{}):Promise<Attachment>{
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
    onProgress(Math.round(Math.min(offset+part.length,bytes.length)/bytes.length*100));
  }
  ensureActive();
  return request<Attachment>('/web/uploads/finish',{id:upload.id});
}
export async function downloadFile(file:Attachment){
  const bytes=new Uint8Array(file.size);
  for(let offset=0,index=0;offset<bytes.length;index++){
    const part=await request<{data:string;chunk_size:number}>('/web/uploads/get',{id:file.id,index});
    const chunk=Uint8Array.from(atob(part.data),c=>c.charCodeAt(0));
    if(!chunk.length||offset+chunk.length>bytes.length)throw new Error('Некорректный файл.');
    bytes.set(chunk,offset);offset+=chunk.length;
  }
  if(await sha256(bytes)!==file.sha256)throw new Error('Контрольная сумма файла не совпала.');
  const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download=file.name;anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),30000);
}

