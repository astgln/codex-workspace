import {decode, encode, keyId, signerId} from './envelope';

export type ScopeKey = {scope: string; epoch: number; key: string; id: string};
export type KeyBundle = {v: 1; workspace: string; origin: string; device: string; authority: string; revision: number; keys: ScopeKey[]};
const utf8 = new TextEncoder();
const fail = () => new Error('Набор ключей не соответствует этому устройству или сайту.');
const exact = (v: unknown, fields: string[]): v is Record<string, unknown> => Boolean(v) && typeof v === 'object' && !Array.isArray(v) &&
  Object.keys(v as object).sort().join(',') === [...fields].sort().join(',');
const safeInteger = (n: unknown): n is number => typeof n === 'number' && Number.isSafeInteger(n) && n >= 1;
const scope = (s: unknown): s is string => typeof s === 'string' && utf8.encode(s).length > 0 && utf8.encode(s).length <= 512 &&
  new TextDecoder('utf-8', {fatal: true}).decode(utf8.encode(s)) === s;
export const bytes = (value: Uint8Array): ArrayBuffer => new Uint8Array(value).buffer;

export async function importAuthority(spki: unknown): Promise<CryptoKey> {
  const raw = decode(spki, 256);
  const result = await crypto.subtle.importKey('spki', bytes(raw), {name: 'ECDSA', namedCurve: 'P-256'}, true, ['verify']);
  if (encode(new Uint8Array(await crypto.subtle.exportKey('spki', result))) !== spki) throw fail();
  return result;
}

export async function validateKeys(input: unknown): Promise<ScopeKey[]> {
  if (!Array.isArray(input) || input.length > 10000) throw fail();
  const seen = new Set<string>(), ids = new Set<string>();
  const result: ScopeKey[] = [];
  for (const entry of input) {
    if (!exact(entry, ['scope', 'epoch', 'key', 'id']) || !scope(entry.scope) || !safeInteger(entry.epoch) ||
      typeof entry.id !== 'string' || typeof entry.key !== 'string' || await keyId(decode(entry.key, 32, 32)) !== entry.id) throw fail();
    const identity = JSON.stringify([entry.scope, entry.epoch]);
    if (seen.has(identity) || ids.has(entry.id)) throw fail();
    seen.add(identity); ids.add(entry.id);
    result.push({scope: entry.scope, epoch: entry.epoch, key: entry.key, id: entry.id});
  }
  return result;
}

export async function validateBundle(input: unknown, expected: {workspace: string; origin: string; device: CryptoKey; authority: string}): Promise<KeyBundle> {
  if (!exact(input, ['v', 'workspace', 'origin', 'device', 'authority', 'revision', 'keys']) || input.v !== 1 ||
    input.workspace !== expected.workspace || input.origin !== expected.origin || input.device !== await signerId(expected.device) ||
    input.authority !== expected.authority || !safeInteger(input.revision) || !scope(input.workspace)) throw fail();
  const url = new URL(expected.origin);
  if (url.protocol !== 'https:' || url.origin !== expected.origin) throw fail();
  await importAuthority(input.authority);
  return {v: 1, workspace: expected.workspace, origin: expected.origin, device: input.device as string,
    authority: expected.authority, revision: input.revision, keys: await validateKeys(input.keys)};
}

export function decodeObject(raw: Uint8Array): unknown {
  if (raw.length > 4 * 1024 * 1024) throw fail();
  // Authenticated endpoint serialization is JSON. Strict field checks follow parsing;
  // no property of a parsed object is used for trust before validation.
  try {return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(raw));} catch {throw fail();}
}
