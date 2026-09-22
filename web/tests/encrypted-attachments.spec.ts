import {test, expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

test('browser encrypts an attachment Python can verify without plaintext upload metadata', async ({page}) => {
  await page.goto('/');
  const calls: {path:string;body:Record<string,unknown>}[] = [];
  await page.route('**/web/e2ee/files/*', async route => {
    const body=route.request().postDataJSON();const path=new URL(route.request().url()).pathname;
    calls.push({path,body});
    await route.fulfill({json:path.endsWith('/start')?{id:body.id,chunk_size:48*1024}:{ok:true}});
  });
  const result = await page.evaluate(async () => {
    // @ts-expect-error Vite test import.
    const c=await import('/src/crypto/envelope.ts');
    // @ts-expect-error Vite test import.
    const a=await import('/src/crypto/attachments.ts');
    const raw=crypto.getRandomValues(new Uint8Array(32));
    const key={scope:'task',epoch:1,key:c.encode(raw),id:await c.keyId(raw)};
    const device=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},false,['sign','verify']);
    const file=new File(['private-test-file-content\n'.repeat(4000)],'private-test-filename.log');
    const prepared=await a.encryptAttachment(file,'workspace',key,device);
    await a.uploadEncryptedAttachment('workspace','task',prepared);
    return {workspace:'workspace',scope:'task',key:key.key,
      public:c.encode(new Uint8Array(await crypto.subtle.exportKey('spki',device.publicKey))),
      manifest:prepared.manifest,encrypted:c.encode(prepared.encrypted)};
  });
  const python=process.env.CRYPTO_TEST_PYTHON || fileURLToPath(new URL('../../.local/crypto-venv/bin/python',import.meta.url));
  const helper=fileURLToPath(new URL('../../tests/attachment_vectors.py',import.meta.url));
  const opened=JSON.parse(execFileSync(python,[helper],{input:JSON.stringify(result),encoding:'utf8'}));
  expect(opened).toEqual({size:result.manifest.size,sha256:result.manifest.sha256});
  expect(calls.length).toBeGreaterThan(3);
  const transmitted=JSON.stringify(calls);
  for (const forbidden of ['private-test-file-content','private-test-filename.log',result.manifest.sha256,result.key])
    expect(transmitted).not.toContain(forbidden);
  expect(calls[0].body.sha256).toBe(result.manifest.ciphertext_sha256);
});


test('download authenticates ciphertext, task and sender before returning bytes',async({page})=>{
 await page.goto('/');
 const fixture=await page.evaluate(async()=>{
  // @ts-expect-error Vite test module
  const c=await import('/src/crypto/envelope.ts');
  // @ts-expect-error Vite test module
  const a=await import('/src/crypto/attachments.ts');
  const raw=crypto.getRandomValues(new Uint8Array(32));
  const key={scope:'task',epoch:1,key:c.encode(raw),id:await c.keyId(raw)};
  const signer=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
  const prepared=await a.encryptAttachment(new File(['secret attachment'], 'test.log'),'workspace',key,signer);
  return {...prepared,encrypted:Array.from(prepared.encrypted),key,publicKey:c.encode(new Uint8Array(await crypto.subtle.exportKey('spki',signer.publicKey)))};
 });
 let tamper=false;
 await page.route('**/web/e2ee/files/*',async r=>{
  if(r.request().url().endsWith('/describe'))return r.fulfill({json:{id:fixture.manifest.id,size:fixture.encrypted.length,sha256:fixture.manifest.ciphertext_sha256,chunk_size:48*1024}});
  const data=Uint8Array.from(fixture.encrypted);if(tamper)data[100]^=1;
  return r.fulfill({json:{data:Buffer.from(data).toString('base64url')}});
 });
 const run=()=>page.evaluate(async fixture=>{
  // @ts-expect-error Vite test module
  const a=await import('/src/crypto/attachments.ts');
  const bundle={keys:[fixture.key]};
  const bytes=await a.downloadEncryptedAttachment('workspace','task',fixture.manifest,fixture.publicKey,bundle,()=>{});
  return new TextDecoder().decode(bytes);
 },fixture);
 expect(await run()).toBe('secret attachment');
 tamper=true;await expect(run()).rejects.toThrow('Шифрованное вложение изменено');
});
