import {bytes, type ScopeKey} from './bundle';
import {encode, decode, seal} from './envelope';
import {request} from '../api/transport';

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

export async function uploadEncryptedAttachment(workspace: string, scope: string, prepared: Awaited<ReturnType<typeof encryptAttachment>>) {
  const {manifest,encrypted} = prepared;
  if (encrypted.length > 8*1024*1024 || await hash(encrypted) !== manifest.ciphertext_sha256) throw new Error('Шифрованное вложение изменилось.');
  const identity = {workspace,scope,id:manifest.id};
  const started = await request<{id:string;chunk_size:number}>('/web/e2ee/files/start',
    {...identity,size:encrypted.length,sha256:manifest.ciphertext_sha256});
  if (started.id !== manifest.id || started.chunk_size !== CHUNK) throw new Error('Сервер вернул некорректные параметры загрузки.');
  for (let offset=0;offset<encrypted.length;offset+=CHUNK) {
    const result = await request<{ok:boolean}>('/web/e2ee/files/chunk', {...identity,index:offset/CHUNK,data:encode(encrypted.subarray(offset,offset+CHUNK))});
    if (result.ok !== true) throw new Error('Загрузка шифрованного вложения не подтверждена.');
  }
  const result = await request<{ok:boolean}>('/web/e2ee/files/finish', identity);
  if (result.ok !== true) throw new Error('Шифрованное вложение не проверено сервером.');
  return manifest;
}
