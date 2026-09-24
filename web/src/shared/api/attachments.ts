import {encryptedUpload,encryptedDownload} from '../../features/encryption/client';
import type {Attachment} from './types';
export async function uploadFile(thread:string,file:File,onProgress:(percent:number)=>void,ensureActive:()=>void=()=>{}):Promise<Attachment>{
 const result=await encryptedUpload(thread,file,ensureActive);
 onProgress(100);return result;
}
export async function downloadFile(file:Attachment){
 const bytes=await encryptedDownload(file);
 const url=URL.createObjectURL(new Blob([new Uint8Array(bytes).buffer],{type:'application/octet-stream'}));
 const anchor=document.createElement('a');anchor.href=url;anchor.download=file.name;anchor.click();
 setTimeout(()=>URL.revokeObjectURL(url),30000);
}
