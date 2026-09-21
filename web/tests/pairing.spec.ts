import {test, expect} from '@playwright/test';

test('pairing uses a fragment, pins the authority, and rejects expired links', async ({page}) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    // @ts-expect-error Vite serves endpoint crypto directly for these tests.
    const c = await import('/src/crypto/envelope.ts');
    // @ts-expect-error Vite serves endpoint crypto directly for these tests.
    const p = await import('/src/crypto/pairing.ts');
    const authority = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
    const device = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, false, ['sign', 'verify']);
    const now = Math.floor(Date.now() / 1000);
    const invite = {v: 1, workspace: 'workspace', id: c.encode(crypto.getRandomValues(new Uint8Array(32))),
      secret: c.encode(crypto.getRandomValues(new Uint8Array(32))),
      authority: c.encode(new Uint8Array(await crypto.subtle.exportKey('spki', authority.publicKey))), expires: now + 600};
    const link = new URL(await p.pairingLink('https://workspace.example', invite));
    const parsed = await p.parsePairingFragment(link.hash, now);
    const offer = await p.createPairingOffer(parsed, device, now);
    const proof = await c.openEnvelope(c.decode(invite.secret, 32), device.publicKey,
      [invite.workspace, 'devices', 'key-wrap', invite.id, 1], offer.envelope);
    const bundle = {v:1, workspace:invite.workspace, origin:'https://workspace.example', device:await c.signerId(device.publicKey),
      authority:invite.authority, revision:1, keys:[]};
    const grant = await c.seal(c.decode(invite.secret, 32), authority,
      [invite.workspace, 'devices', 'key-wrap', invite.id, 2], new TextEncoder().encode(JSON.stringify(bundle)));
    const opened = await p.openPairingGrant(parsed, grant, device.publicKey, 'https://workspace.example', now);
    let expired = false, wrongAuthority = false, wrongOrigin = false, query = false;
    try {await p.parsePairingFragment(link.hash, now + 600);} catch {expired = true;}
    const forged = await c.seal(c.decode(invite.secret, 32), device,
      [invite.workspace, 'devices', 'key-wrap', invite.id, 2], new TextEncoder().encode('forged'));
    try {await p.openPairingGrant(parsed, forged, device.publicKey, 'https://workspace.example', now);} catch {wrongAuthority = true;}
    try {await p.pairingLink('http://workspace.example', invite);} catch {wrongOrigin = true;}
    try {await p.pairingLink('https://workspace.example/?secret=oops', invite);} catch {query = true;}
    return {same: JSON.stringify(parsed) === JSON.stringify(invite), search: link.search,
      proof: new TextDecoder().decode(proof), recipientMatches: opened.device === await c.signerId(device.publicKey),
      expired, wrongAuthority, wrongOrigin, query, privateExportable: device.privateKey.extractable};
  });
  expect(result).toEqual({same: true, search: '', proof: 'codex-workspace/device-pairing/v1', recipientMatches: true,
    expired: true, wrongAuthority: true, wrongOrigin: true, query: true, privateExportable: false});
});
