import {test, expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const python = process.env.CRYPTO_TEST_PYTHON || fileURLToPath(new URL('../../.local/crypto-venv/bin/python', import.meta.url));
const helper = fileURLToPath(new URL('../../tests/vault_vectors.py', import.meta.url));
const workspace = Buffer.alloc(32, 'w').toString('base64url');

test('keys survive a new tab and reject rollback, recipient changes and local removal races', async ({page, context}) => {
  await page.goto('/');
  const publicKey = await page.evaluate(async workspace => {
    // @ts-expect-error Vite test import.
    const v = await import('/src/features/encryption/vault.ts');
    const [first, second] = await Promise.all([v.getOrCreateDevice('10', workspace), v.getOrCreateDevice('10', workspace)]);
    if (first.deviceStamp !== second.deviceStamp) throw new Error('Concurrent device creation split the keys');
    if (first.signing.privateKey.extractable) throw new Error('Signing key must not be exportable');
    return v.publicDeviceKey(first);
  }, workspace);
  const fixtures = JSON.parse(execFileSync(python, [helper], {encoding: 'utf8', input: JSON.stringify({
    origin: 'https://workspace.example', public: publicKey, workspace})}));
  await page.evaluate(async f => {
    // @ts-expect-error Vite test import.
    const v = await import('/src/features/encryption/vault.ts');
    await v.installBundle('10', f.initial, {workspace: f.initial.workspace, origin: f.initial.origin, authority: f.initial.authority});
  }, fixtures);
  const next = await context.newPage(); await next.goto('/');
  const result = await next.evaluate(async ({f, workspace}) => {
    // @ts-expect-error Vite test import.
    const v = await import('/src/features/encryption/vault.ts');
    const restored = await v.loadDevice('10', workspace);
    const expected = {workspace, origin: f.latest.origin, authority: f.latest.authority};
    await v.installBundle('10', f.latest, expected);
    let rollback = false, otherDevice = false;
    try {await v.installBundle('10', f.initial, expected);} catch {rollback = true;}
    await v.getOrCreateDevice('11', workspace);
    try {await v.installBundle('11', f.latest, expected);} catch {otherDevice = true;}
    const newest = await v.loadDevice('10', workspace);
    await v.forgetDevice('10', workspace);
    await v.getOrCreateDevice('10', workspace);
    let forgotten = false;
    try {await v.installBundle('10', f.latest, expected);} catch {forgotten = true;}
    return {restored: restored.bundle.keys.length, latest: newest.bundle.keys.length, rollback, otherDevice, forgotten,
      oldPublic: await v.publicDeviceKey(restored), privateExportable: newest.signing.privateKey.extractable};
  }, {f: fixtures, workspace});
  expect(result).toEqual({restored: 1, latest: 2, rollback: true, otherDevice: true, forgotten: true,
    oldPublic: publicKey, privateExportable: false});
});

test('browser restores the Python recovery archive and rejects wrong code, origin and revision', async ({page}) => {
  await page.goto('/');
  const publicKey = await page.evaluate(async workspace => {
    // @ts-expect-error Vite test import.
    const v = await import('/src/features/encryption/vault.ts');
    return v.publicDeviceKey(await v.getOrCreateDevice('10', workspace));
  }, workspace);
  const fixtures = JSON.parse(execFileSync(python, [helper], {encoding: 'utf8', input: JSON.stringify({
    origin: 'https://workspace.example', public: publicKey, workspace})}));
  const result = await page.evaluate(async f => {
    // @ts-expect-error Vite test import.
    const r = await import('/src/features/encryption/recovery.ts');
    // @ts-expect-error Vite test import.
    const c = await import('/src/features/encryption/envelope.ts');
    const recovered = await r.readRecovery(f.recovery, f.code, f.latest.origin);
    const checks = [];
    for (const [code, origin, revision] of [[await c.createRecoveryCode(), f.latest.origin, 1],
      [f.code, 'https://wrong.example', 1], [f.code, f.latest.origin, f.recovery.revision + 1]]) {
      try {await r.readRecovery(f.recovery, code, origin, revision); checks.push(false);} catch {checks.push(true);}
    }
    return {keys: recovered.keys, privateExportable: recovered.signing.extractable, checks};
  }, fixtures);
  expect(result.keys).toEqual(fixtures.latest.keys);
  expect(result.privateExportable).toBe(false);
  expect(result.checks).toEqual([true, true, true]);
});
