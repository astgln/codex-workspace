import {bytes, importAuthority, type ScopeKey, type KeyBundle} from './bundle';
import {encode, decode, seal, openEnvelope, type Envelope} from './envelope';
import {request} from '../../shared/api/transport';

export type AttachmentManifest = {id: string; name: string; size: number; sha256: string; ciphertext_sha256: string};
const CHUNK = 48 * 1024;
export const hash = async (raw: Uint8Array) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes(raw))),
  b => b.toString(16).padStart(2,'0')).join('');

export async function encryptAttachment(file: File, workspace: string, key: ScopeKey, device: CryptoKeyPair) {
  if (file.size < 1 || file.size > 5*1024*1024 || !file.name || new TextEncoder().encode(file.name).length > 200 ||
    /[\x00-\x1f\x7f/\\]/.test(file.name) || file.name === '.' || file.name === '..') throw new Error('Некорректное вложение.');
  const plaintext = new Uint8Array(await file.arrayBuffer());
  const id = encode(crypto.getRandomValues(new Uint8Array(32)));
  const envelope = await seal(decode(key.key,32,32),device,[workspace,key.scope,'attachment',id,1],plaintext);
  const encrypted = new TextEncoder().encode(JSON.stringify(envelope));
  const manifest: AttachmentManifest = {id,name:file.name,size:plaintext.length,sha256:await hash(plaintext),ciphertext_sha256:await hash(encrypted)};
  return {manifest,encrypted};
}

export async function uploadEncryptedAttachment(workspace: string, scope: string, prepared: Awaited<ReturnType<typeof encryptAttachment>>, ensureActive:()=>void=()=>{}) {
  const {manifest,encrypted} = prepared;
  if (encrypted.length > 8*1024*1024 || await hash(encrypted) !== manifest.ciphertext_sha256) throw new Error('Шифрованное вложение изменилось.');
  const identity = {workspace,scope,id:manifest.id};
  ensureActive();
  const started = await request<{id:string;chunk_size:number}>('/web/e2ee/files/start',
    {...identity,size:encrypted.length,sha256:manifest.ciphertext_sha256});
  if (started.id !== manifest.id || started.chunk_size !== CHUNK) throw new Error('Сервер вернул некорректные параметры загрузки.');
  for (let offset=0;offset<encrypted.length;offset+=CHUNK) {
    ensureActive();
    const result = await request<{ok:boolean}>('/web/e2ee/files/chunk', {...identity,index:offset/CHUNK,data:encode(encrypted.subarray(offset,offset+CHUNK))});
    if (result.ok !== true) throw new Error('Загрузка шифрованного вложения не подтверждена.');
  }
  ensureActive();
  const result = await request<{ok:boolean}>('/web/e2ee/files/finish', identity);
  if (result.ok !== true) throw new Error('Шифрованное вложение не проверено сервером.');
  return manifest;
}

/** The manifest and signer must come from a verified endpoint-signed response. */
export async function downloadEncryptedAttachment(workspace:string,scope:string,manifest:AttachmentManifest,
  signer:string,bundle:KeyBundle,ensureActive:()=>void):Promise<Uint8Array>{
  if(!Number.isSafeInteger(manifest.size)||manifest.size<1||manifest.size>5*1024*1024||
    !/^[a-f0-9]{64}$/.test(manifest.sha256)||!/^[a-f0-9]{64}$/.test(manifest.ciphertext_sha256))throw new Error('Некорректное вложение.');
  const identity={workspace,scope,id:manifest.id};ensureActive();
  const description=await request<{id:string;size:number;sha256:string;chunk_size:number}>('/web/e2ee/files/describe',identity);
  if(description.id!==manifest.id||description.sha256!==manifest.ciphertext_sha256||description.chunk_size!==CHUNK||
    !Number.isSafeInteger(description.size)||description.size<1||description.size>8*1024*1024)throw new Error('Описание вложения изменено.');
  const encrypted=new Uint8Array(description.size);
  for(let offset=0;offset<encrypted.length;offset+=CHUNK){
    ensureActive();
    const reply=await request<{data:string}>('/web/e2ee/files/get',{...identity,index:offset/CHUNK});
    encrypted.set(decode(reply.data,CHUNK,Math.min(CHUNK,encrypted.length-offset)),offset);
  }
  if(await hash(encrypted)!==manifest.ciphertext_sha256)throw new Error('Шифрованное вложение изменено.');
  const envelope=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(encrypted)) as Envelope;
  const key=bundle.keys.find(k=>k.scope===scope&&k.id===envelope?.key_id);
  if(!key)throw new Error('Нет ключа вложения.');
  const plaintext=await openEnvelope(decode(key.key,32,32),await importAuthority(signer),[workspace,scope,'attachment',manifest.id,1],envelope);
  if(plaintext.length!==manifest.size||await hash(plaintext)!==manifest.sha256)throw new Error('Контрольная сумма вложения не совпала.');
  ensureActive();return plaintext;
}
