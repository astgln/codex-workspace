import {bytes, decodeObject, importAuthority, validateKeys, type ScopeKey} from './bundle';
import {decode, openEnvelope, recoveryKey, signerId} from './envelope';

export type RecoveryMaterial = {workspace: string; origin: string; revision: number; authority: CryptoKey;
  signing: CryptoKey; keys: ScopeKey[]};
const fail = () => new Error('Не удалось проверить пакет восстановления для этого сайта.');
const exact = (v: unknown, fields: string[]): v is Record<string, unknown> => Boolean(v) && typeof v === 'object' && !Array.isArray(v) &&
  Object.keys(v as object).sort().join(',') === [...fields].sort().join(',');

export async function readRecovery(packet: unknown, code: string, expectedOrigin: string, minimumRevision = 1): Promise<RecoveryMaterial> {
  if (!exact(packet, ['v', 'workspace', 'authority', 'revision', 'envelope']) || packet.v !== 1 ||
    typeof packet.workspace !== 'string' || typeof packet.authority !== 'string' || typeof packet.revision !== 'number' ||
    !Number.isSafeInteger(packet.revision) || packet.revision < minimumRevision || packet.revision < 1) throw fail();
  decode(packet.workspace, 32, 32);
  const authority = await importAuthority(packet.authority);
  const content = await openEnvelope(await recoveryKey(code), authority,
    [packet.workspace, 'recovery', 'key-wrap', 'authority-backup', packet.revision], packet.envelope);
  const value = decodeObject(content);
  if (!exact(value, ['v', 'workspace', 'origin', 'authority_private', 'revision', 'keys']) || value.v !== 1 ||
    value.workspace !== packet.workspace || value.origin !== expectedOrigin || value.revision !== packet.revision ||
    new URL(expectedOrigin).protocol !== 'https:' || new URL(expectedOrigin).origin !== expectedOrigin) throw fail();
  const privateBytes = decode(value.authority_private, 512);
  // Temporarily export public coordinates to verify that the encrypted private key
  // actually belongs to the authority that signed the package. Do not persist it.
  const inspection = await crypto.subtle.importKey('pkcs8', bytes(privateBytes), {name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign']);
  const jwk = await crypto.subtle.exportKey('jwk', inspection);
  const publicPart = await crypto.subtle.importKey('jwk', {kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y},
    {name: 'ECDSA', namedCurve: 'P-256'}, true, ['verify']);
  delete jwk.d;
  if (await signerId(publicPart) !== await signerId(authority)) throw fail();
  const signing = await crypto.subtle.importKey('pkcs8', bytes(privateBytes), {name: 'ECDSA', namedCurve: 'P-256'}, false, ['sign']);
  privateBytes.fill(0); content.fill(0);
  return {workspace: packet.workspace, origin: expectedOrigin, revision: packet.revision,
    authority, signing, keys: await validateKeys(value.keys)};
}
