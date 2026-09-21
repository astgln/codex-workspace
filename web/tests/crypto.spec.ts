import {test, expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const python = process.env.CRYPTO_TEST_PYTHON || fileURLToPath(new URL('../../.local/crypto-venv/bin/python', import.meta.url));
const vectorScript = fileURLToPath(new URL('../../tests/crypto_vectors.py', import.meta.url));
const fixture = () => JSON.parse(execFileSync(python, [vectorScript, 'generate'], {encoding: 'utf8'}));

test('Python and browser authenticate and decrypt each other, including recovery keys', async ({page}) => {
  const vector = fixture();
  await page.goto('/');
  const result = await page.evaluate(async (v) => {
    // @ts-expect-error Vite serves this test import in the browser.
    const c = await import('/src/crypto/envelope.ts');
    const publicKey = await crypto.subtle.importKey('spki', c.decode(v.public, 256), {name: 'ECDSA', namedCurve: 'P-256'}, true, ['verify']);
    const privateKey = await crypto.subtle.importKey('pkcs8', c.decode(v.private, 512), {name: 'ECDSA', namedCurve: 'P-256'}, false, ['sign']);
    const plaintext = await c.openEnvelope(c.decode(v.key, 32), publicKey, v.context, v.envelope);
    const envelope = await c.seal(c.decode(v.key, 32), {publicKey, privateKey}, v.context, plaintext);
    const recovered = c.encode(await c.recoveryKey(v.recovery));
    const recovery = await c.createRecoveryCode();
    return {plaintext: c.encode(plaintext), envelope, recovered, recovery, recovery_key: c.encode(await c.recoveryKey(recovery))};
  }, vector);
  expect(result.plaintext).toBe(vector.plaintext);
  expect(result.recovered).toBe(vector.recovery_key);
  const opened = JSON.parse(execFileSync(python, [vectorScript, 'open'], {
    input: JSON.stringify({...vector, envelope: result.envelope, recovery: result.recovery}), encoding: 'utf8'}));
  expect(opened.plaintext).toBe(vector.plaintext);
  expect(opened.recovery_key).toBe(result.recovery_key);
});

test('browser rejects changed context, ciphertext, signer, version and plaintext fallback', async ({page}) => {
  await page.goto('/');
  const checks = await page.evaluate(async v => {
    // @ts-expect-error Vite serves this test import in the browser.
    const c = await import('/src/crypto/envelope.ts');
    const publicKey = await crypto.subtle.importKey('spki', c.decode(v.public, 256), {name: 'ECDSA', namedCurve: 'P-256'}, true, ['verify']);
    const impostor = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
    const key = c.decode(v.key, 32);
    const corrupt = (field: string) => {const e = structuredClone(v.envelope); const b = c.decode(e[field], 10000); b[0] ^= 1; e[field] = c.encode(b); return e;};
    const swapped = structuredClone(v.envelope); swapped.context[1] = 'different-task';
    const cases = [null, 'plaintext', {}, {...v.envelope, v: 2}, {...v.envelope, v: true},
      {...v.envelope, plaintext: 'hidden downgrade'}, {...v.envelope, nonce: v.envelope.nonce + '='},
      corrupt('salt'), corrupt('nonce'), corrupt('ciphertext'), corrupt('signature'), swapped,
      await c.seal(key, impostor, v.context, new TextEncoder().encode('forged'))];
    const rejected = [];
    for (const e of cases) {
      try {await c.openEnvelope(key, publicKey, v.context, e); rejected.push(false);} catch {rejected.push(true);}
    }
    // Even when the relay rewrites both the request route and envelope context, the signature fails.
    try {await c.openEnvelope(key, publicKey, swapped.context, swapped); rejected.push(false);} catch {rejected.push(true);}
    return rejected;
  }, fixture());
  expect(checks.length).toBe(14);
  expect(checks.every(Boolean)).toBe(true);
});
