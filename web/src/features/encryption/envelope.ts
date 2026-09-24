/** Trusted-endpoint crypto. This module must never be included in relay handlers. */
export const MAX_PLAINTEXT = 6 * 1024 * 1024;
export type Kind = 'request' | 'response' | 'history' | 'catalog' | 'attachment' | 'push' | 'key-wrap' | 'control' | 'control-result';
export type Context = [workspace: string, scope: string, kind: Kind, record: string, revision: number];
export type Envelope = {v: 1; context: Context; key_id: string; signer: string;
  salt: string; nonce: string; ciphertext: string; signature: string};
const kinds = new Set(['request', 'response', 'history', 'catalog', 'attachment', 'push', 'key-wrap', 'control', 'control-result']);
const fields = ['v', 'context', 'key_id', 'signer', 'salt', 'nonce', 'ciphertext', 'signature'].sort();
const utf8 = new TextEncoder();
const domain = utf8.encode('codex-workspace/e2ee/v1');
const error = () => new Error('Encrypted data verification failed');
// Copy into an owned ArrayBuffer for WebCrypto (and never accept shared memory).
const buffer = (value: Uint8Array): ArrayBuffer => new Uint8Array(value).buffer;
export function encode(value: Uint8Array): string {
  let binary = '';
  for (let start = 0; start < value.length; start += 8192)
    binary += String.fromCharCode(...value.subarray(start, start + 8192));
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
export function decode(value: unknown, maximum: number, exact?: number): Uint8Array {
  if (typeof value !== 'string' || value.length > Math.floor((maximum * 4 + 2) / 3) || !/^[A-Za-z0-9_-]*$/.test(value)) throw error();
  try {
    const raw = Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
    if (raw.length > maximum || (exact !== undefined && raw.length !== exact) || encode(raw) !== value) throw error();
    return raw;
  } catch { throw error(); }
}
function frame(...parts: Uint8Array[]): Uint8Array {
  const result = new Uint8Array(parts.reduce((total, part) => total + 4 + part.length, 0));
  const view = new DataView(result.buffer);
  let offset = 0;
  for (const part of parts) {view.setUint32(offset, part.length); offset += 4; result.set(part, offset); offset += part.length;}
  return result;
}
function context(value: Context): Context {
  if (!Array.isArray(value) || value.length !== 5 || !value.slice(0, 4).every(v =>
    typeof v === 'string' && utf8.encode(v).length > 0 && utf8.encode(v).length <= 512 &&
    new TextDecoder('utf-8', {fatal: true}).decode(utf8.encode(v)) === v) ||
    !kinds.has(value[2]) || !Number.isSafeInteger(value[4]) || value[4] < 1) throw error();
  return value;
}
function symmetric(key: Uint8Array) {
  if (!(key instanceof Uint8Array) || key.length !== 32) throw error();
}
export async function keyId(key: Uint8Array): Promise<string> {
  symmetric(key);
  return encode(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer(frame(domain, utf8.encode('key-id'), key)))));
}
export async function signerId(key: CryptoKey): Promise<string> {
  const algorithm = key.algorithm as EcKeyAlgorithm;
  if (key.type !== 'public' || algorithm.name !== 'ECDSA' || algorithm.namedCurve !== 'P-256') throw error();
  const spki = await crypto.subtle.exportKey('spki', key);
  return encode(new Uint8Array(await crypto.subtle.digest('SHA-256', spki)));
}
function aad(value: Context, kid: string, signer: string) {
  context(value);
  return frame(domain, utf8.encode('envelope'), ...value.map(v => utf8.encode(String(v))), utf8.encode(kid), utf8.encode(signer));
}
async function derive(key: Uint8Array, salt: Uint8Array, associated: Uint8Array) {
  const source = await crypto.subtle.importKey('raw', buffer(key), 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey({name: 'HKDF', hash: 'SHA-256', salt: buffer(salt),
    info: buffer(frame(domain, utf8.encode('content-key'), associated))}, source,
    {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
}
function signed(associated: Uint8Array, salt: Uint8Array, nonce: Uint8Array, ciphertext: Uint8Array) {
  return frame(domain, utf8.encode('signature'), associated, salt, nonce, ciphertext);
}
export async function seal(key: Uint8Array, signing: CryptoKeyPair, expected: Context, plaintext: Uint8Array): Promise<Envelope> {
  symmetric(key); context(expected);
  if (!(plaintext instanceof Uint8Array) || plaintext.length > MAX_PLAINTEXT) throw error();
  const key_id = await keyId(key), signer = await signerId(signing.publicKey);
  const associated = aad(expected, key_id, signer);
  const salt = crypto.getRandomValues(new Uint8Array(32)), nonce = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv: buffer(nonce),
    additionalData: buffer(associated), tagLength: 128}, await derive(key, salt, associated), buffer(plaintext)));
  const signature = new Uint8Array(await crypto.subtle.sign({name: 'ECDSA', hash: 'SHA-256'}, signing.privateKey,
    buffer(signed(associated, salt, nonce, ciphertext))));
  // Detect accidental public/private key mismatches before anything leaves the endpoint.
  if (!await crypto.subtle.verify({name: 'ECDSA', hash: 'SHA-256'}, signing.publicKey, buffer(signature),
    buffer(signed(associated, salt, nonce, ciphertext)))) throw error();
  return {v: 1, context: [...expected], key_id, signer, salt: encode(salt), nonce: encode(nonce),
    ciphertext: encode(ciphertext), signature: encode(signature)};
}
export async function openEnvelope(key: Uint8Array, trustedSigner: CryptoKey, expected: Context, input: unknown): Promise<Uint8Array> {
  symmetric(key); context(expected);
  if (!input || typeof input !== 'object' || Array.isArray(input) || JSON.stringify(Object.keys(input).sort()) !== JSON.stringify(fields)) throw error();
  const envelope = input as Envelope;
  if (envelope.v !== 1 || !Array.isArray(envelope.context) || envelope.context.length !== 5 ||
    envelope.context.some((v, i) => v !== expected[i]) || envelope.key_id !== await keyId(key) ||
    envelope.signer !== await signerId(trustedSigner)) throw error();
  const salt = decode(envelope.salt, 32, 32), nonce = decode(envelope.nonce, 12, 12);
  const ciphertext = decode(envelope.ciphertext, MAX_PLAINTEXT + 16), signature = decode(envelope.signature, 64, 64);
  if (ciphertext.length < 16) throw error();
  const associated = aad(expected, envelope.key_id, envelope.signer);
  try {
    if (!await crypto.subtle.verify({name: 'ECDSA', hash: 'SHA-256'}, trustedSigner, buffer(signature),
      buffer(signed(associated, salt, nonce, ciphertext)))) throw error();
    return new Uint8Array(await crypto.subtle.decrypt({name: 'AES-GCM', iv: buffer(nonce),
      additionalData: buffer(associated), tagLength: 128}, await derive(key, salt, associated), buffer(ciphertext)));
  } catch { throw error(); }
}
export async function createRecoveryCode(): Promise<string> {
  const seed = crypto.getRandomValues(new Uint8Array(32));
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', buffer(frame(domain, utf8.encode('recovery'), seed))));
  const raw = new Uint8Array(36); raw.set(seed); raw.set(hash.subarray(0, 4), 32);
  return 'cw1_' + encode(raw);
}
export async function recoveryKey(code: string): Promise<Uint8Array> {
  if (typeof code !== 'string' || !code.startsWith('cw1_')) throw error();
  const raw = decode(code.slice(4), 36, 36), seed = raw.subarray(0, 32);
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', buffer(frame(domain, utf8.encode('recovery'), seed))));
  let difference = 0;
  for (let i = 0; i < 4; i++) difference |= raw[32 + i] ^ hash[i];
  if (difference !== 0) throw error();
  const source = await crypto.subtle.importKey('raw', buffer(seed), 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({name: 'HKDF', hash: 'SHA-256', salt: new ArrayBuffer(0),
    info: buffer(frame(domain, utf8.encode('recovery-key')))}, source, 256));
}
