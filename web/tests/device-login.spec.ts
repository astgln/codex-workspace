import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

test('device login signs an origin-bound challenge that Python verifies; private key stays local',async({page})=>{
 const workspace=Buffer.alloc(32,119).toString('base64url');
 let loggedIn=false;let challenge:any;let proof:any;
 await page.route('**/auth/session',r=>r.fulfill(loggedIn?{json:{csrf:'test',workspace:{user:{id:42},encryption:{v:1,workspace},threads:[],messages:[]}}}:{status:401,json:{}}));
 await page.route('**/auth/device/challenge',r=>{
  challenge={origin:'http://127.0.0.1:5173',workspace,nonce:'bm5ubm5ubm5ubm5ubm5ubm5ubm5ubm5ubm5ubm5ubm4',expires:Math.floor(Date.now()/1000)+60};
  return r.fulfill({json:challenge});
 });
 await page.route('**/auth/device/session',r=>{proof=r.request().postDataJSON();loggedIn=true;return r.fulfill({json:{uid:42,ok:true}});});
 await page.goto('/');
 const publicKey=await page.evaluate(async workspace=>{
  // @ts-expect-error Vite test module
  const v=await import('/src/features/encryption/vault.ts');
  // @ts-expect-error Vite test module
  const login=await import('/src/shared/api/login.ts');
  const device=await v.getOrCreateDevice('0',workspace);
  if(device.signing.privateKey.extractable)throw new Error('Private key is exportable');
  const pub=await v.publicDeviceKey(device);
  await login.loginDevice(device);
  const bound=await v.loadDevice('42',workspace);
  if(bound.deviceStamp!==device.deviceStamp||await v.loadDevice('0',workspace))throw new Error('Account binding failed');
  return pub;
 },workspace);
 expect(Object.keys(proof).sort()).toEqual(['device','nonce','signature']);
 const result=execFileSync(process.env.CRYPTO_TEST_PYTHON||'python3',['-c',
  "import json,sys;from codex_workspace.crypto.device_auth import key,message,verify;v=json.load(sys.stdin);c=v['challenge'];p=v['proof'];verify(key(v['public']),p['signature'],message('login',c['origin'],c['workspace'],p['device'],p['nonce'],c['expires']),browser=True);print('verified')"
 ],{input:JSON.stringify({public:publicKey,challenge,proof}),encoding:'utf8'});
 expect(result.trim()).toBe('verified');
});

test('fresh device offers enrollment and never opens Telegram',async({page})=>{
 const external:string[]=[];page.on('request',r=>{if(r.url().includes('telegram'))external.push(r.url());});
 await page.route('**/auth/session',r=>r.fulfill({status:401,json:{}}));
 await page.goto('/');
 await page.getByRole('button',{name:'Войти с ключом устройства'}).click();
 await expect(page.getByRole('alert')).toContainText('нет ключа');
 await page.getByText('Новое устройство',{exact:true}).click();
 await expect(page.getByLabel('Ссылка привязки')).toBeVisible();
 expect(external).toEqual([]);
});
