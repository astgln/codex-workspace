import {decode, encode, openEnvelope, seal, signerId, type Envelope} from './envelope';

export type Invitation = {v: 1; workspace: string; id: string; secret: string; authority: string; expires: number};
const text = new TextEncoder();
const failure = () => new Error('Pairing invitation is invalid or expired');
const buffer = (bytes: Uint8Array): ArrayBuffer => new Uint8Array(bytes).buffer;

export async function validateInvitation(input: unknown, now = Math.floor(Date.now() / 1000)): Promise<Invitation> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw failure();
  const v = input as Invitation;
  if (Object.keys(v).sort().join(',') !== 'authority,expires,id,secret,v,workspace' || v.v !== 1 ||
    typeof v.workspace !== 'string' || !v.workspace || text.encode(v.workspace).length > 512 ||
    !Number.isSafeInteger(v.expires) || v.expires <= now || v.expires > now + 600) throw failure();
  decode(v.id, 32, 32); decode(v.secret, 32, 32);
  const authority = await crypto.subtle.importKey('spki', buffer(decode(v.authority, 256)),
    {name: 'ECDSA', namedCurve: 'P-256'}, true, ['verify']);
  // Require canonical SPKI, matching the Python endpoint's key fingerprints.
  if (encode(new Uint8Array(await crypto.subtle.exportKey('spki', authority))) !== v.authority) throw failure();
  return {...v};
}

export async function pairingLink(origin: string, invitation: Invitation): Promise<string> {
  const url = new URL(origin);
  if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw failure();
  const checked = await validateInvitation(invitation);
  // Fragment is never part of the HTTP request. Do not put this URL in analytics,
  // logs, screenshots, push notifications, the clipboard without a gesture, or API bodies.
  url.hash = 'pair=' + encode(text.encode(JSON.stringify(checked)));
  return url.href;
}

export async function parsePairingFragment(fragment: string, now = Math.floor(Date.now() / 1000)): Promise<Invitation> {
  if (!fragment.startsWith('#pair=') || fragment.length > 4096) throw failure();
  try {
    const raw = new TextDecoder('utf-8', {fatal: true}).decode(decode(fragment.slice(6), 3000));
    return await validateInvitation(JSON.parse(raw), now);
  } catch { throw failure(); }
}

export async function createPairingOffer(invitation: Invitation, device: CryptoKeyPair, now = Math.floor(Date.now() / 1000)) {
  const checked = await validateInvitation(invitation, now);
  const public_key = encode(new Uint8Array(await crypto.subtle.exportKey('spki', device.publicKey)));
  const envelope = await seal(decode(checked.secret, 32, 32), device,
    [checked.workspace, 'devices', 'key-wrap', checked.id, 1], text.encode('codex-workspace/device-pairing/v1'));
  return {id: checked.id, public_key, envelope};
}

export async function openPairingGrant(invitation: Invitation, envelope: Envelope, now = Math.floor(Date.now() / 1000)) {
  const checked = await validateInvitation(invitation, now);
  const authority = await crypto.subtle.importKey('spki', buffer(decode(checked.authority, 256)),
    {name: 'ECDSA', namedCurve: 'P-256'}, true, ['verify']);
  const bundle = await openEnvelope(decode(checked.secret, 32, 32), authority,
    [checked.workspace, 'devices', 'key-wrap', checked.id, 2], envelope);
  // The caller must validate the bundle schema and the intended device fingerprint
  // before atomically persisting keys. Never install partially decoded bundles.
  return {bundle, authority: await signerId(authority)};
}
