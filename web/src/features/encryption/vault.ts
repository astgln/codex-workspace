/** Persist endpoint keys across tabs. No tokens or secrets are stored in localStorage. */
import {validateBundle, type KeyBundle} from './bundle';
import {encode, signerId} from './envelope';

const DATABASE = 'workspace-endpoint-keys-v1';
export type Device = {identity: string; workspace: string; account: string; signing: CryptoKeyPair; deviceStamp: string; bundle: KeyBundle | null};
const identity = (account: string, workspace: string) => JSON.stringify([account, workspace]);
function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('devices', {keyPath: 'identity'});
    request.onsuccess = () => {request.result.onversionchange = () => request.result.close(); resolve(request.result);};
    request.onerror = () => reject(new Error('Не удалось открыть хранилище ключей устройства.'));
    request.onblocked = () => reject(new Error('Закройте старые вкладки сайта и повторите попытку.'));
  });
}
function operation<T>(db: IDBDatabase, mode: IDBTransactionMode, action: (store: IDBObjectStore, result: (v: T) => void) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('devices', mode);
    let value: T;
    tx.oncomplete = () => resolve(value);
    tx.onerror = tx.onabort = () => reject(new Error('Не удалось сохранить ключи устройства.'));
    try {action(tx.objectStore('devices'), next => {value = next;});} catch (e) {tx.abort(); reject(e);}
  }).finally(() => db.close()) as Promise<T>;
}

export async function loadDevice(account: string, workspace: string): Promise<Device | null> {
  return operation(await openDB(), 'readonly', (store, result) => {
    const request = store.get(identity(account, workspace));
    request.onsuccess = () => result(request.result || null);
  });
}

export async function getOrCreateDevice(account: string, workspace: string): Promise<Device> {
  if (!/^\d{1,20}$/.test(account) || !workspace || workspace.length > 512) throw new Error('Некорректное пространство.');
  const existing = await loadDevice(account, workspace);
  if (existing) return existing;
  // Generation must happen before the transaction; WebCrypto awaits would close it.
  const signing = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, false, ['sign', 'verify']);
  const candidate: Device = {identity: identity(account, workspace), account, workspace, signing,
    deviceStamp: await signerId(signing.publicKey), bundle: null};
  return operation(await openDB(), 'readwrite', (store, result) => {
    const read = store.get(candidate.identity);
    read.onsuccess = () => {
      if (read.result) result(read.result);
      else {store.add(candidate); result(candidate);}
    };
  });
}

export async function installBundle(account: string, raw: unknown, expected: {workspace: string; origin: string; authority: string}): Promise<KeyBundle> {
  const device = await loadDevice(account, expected.workspace);
  if (!device) throw new Error('Устройство ещё не создано.');
  const bundle = await validateBundle(raw, {...expected, device: device.signing.publicKey});
  const fingerprint = await signerId(device.signing.publicKey);
  let refusal: Error | null = null;
  await operation<void>(await openDB(), 'readwrite', (store, result) => {
    const read = store.get(device.identity);
    read.onsuccess = () => {
      const current = read.result as Device | undefined;
      // Compare a persisted fingerprint: CryptoKeys are different structured-clone
      // objects on each read. This also detects forgetting/re-pairing in another tab.
      const stored = current;
      if (!stored || stored.deviceStamp !== fingerprint || (stored.bundle &&
        (stored.bundle.authority !== bundle.authority || stored.bundle.origin !== bundle.origin ||
         stored.bundle.revision > bundle.revision || (stored.bundle.revision === bundle.revision &&
          JSON.stringify(stored.bundle) !== JSON.stringify(bundle))))) {
        refusal = new Error('Ключи изменились в другой вкладке или получен устаревший набор.'); return;
      }
      store.put({...stored, bundle}); result(undefined);
    };
  });
  if (refusal) throw refusal;
  return bundle;
}

export async function forgetDevice(account: string, workspace: string): Promise<void> {
  // Local removal does not revoke remote trust; caller must explicitly revoke first.
  await operation<void>(await openDB(), 'readwrite', (store, result) => {store.delete(identity(account, workspace)); result(undefined);});
}

export async function publicDeviceKey(device: Device): Promise<string> {
  return encode(new Uint8Array(await crypto.subtle.exportKey('spki', device.signing.publicKey)));
}

/** Enumerate only public identity and local keys; nothing is sent until explicit login. */
export async function enrolledDevices():Promise<Device[]>{
 return operation(await openDB(),'readonly',(store,result)=>{
  const read=store.getAll();read.onsuccess=()=>result(read.result.filter((d:Device)=>d.bundle?.origin===location.origin));
 });
}
export async function bindDeviceAccount(device:Device,account:string):Promise<void>{
 if(!/^\d{1,16}$/.test(account))throw new Error('Некорректный аккаунт.');
 let changed=false;
 await operation<void>(await openDB(),'readwrite',(store,result)=>{
  const read=store.get(device.identity);
  read.onsuccess=()=>{
   const saved=read.result as Device|undefined;
   if(!saved||saved.deviceStamp!==device.deviceStamp){changed=true;result(undefined);return;}
   store.put({...saved,account,identity:identity(account,device.workspace)});
   if(saved.identity!==identity(account,device.workspace))store.delete(saved.identity);
   result(undefined);
  };
 });
 if(changed)throw new Error('Ключ устройства изменился.');
}
