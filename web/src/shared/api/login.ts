import {request,restoreSession} from './transport';
import {enrolledDevices,bindDeviceAccount,type Device} from '../../features/encryption/vault';
import {encode} from '../../features/encryption/envelope';
export type LoginConfig={devices:Device[]};
export async function prepareLogin():Promise<LoginConfig>{return {devices:await enrolledDevices()};}
export async function authenticateDevice(device:Device,signal?:AbortSignal){
 const check=()=>{if(signal?.aborted)throw new Error('Вход отменён.');};check();
 const proof=await request<{nonce:string;expires:number;workspace:string;origin:string}>('/auth/device/challenge',{device:device.deviceStamp});check();
 if(proof.origin!==location.origin||proof.workspace!==device.workspace||!Number.isSafeInteger(proof.expires)||proof.expires<=Date.now()/1000||proof.expires>Date.now()/1000+120||!/^[A-Za-z0-9_-]{43}$/.test(proof.nonce))throw new Error('Некорректный запрос входа.');
 const message=new TextEncoder().encode(JSON.stringify(['codex-workspace/device-auth/v1','login',location.origin,device.workspace,device.deviceStamp,proof.nonce,proof.expires]));
 const signature=encode(new Uint8Array(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},device.signing.privateKey,message)));check();
 const result=await request<{uid:number}>('/auth/device/session',{nonce:proof.nonce,device:device.deviceStamp,signature});check();
 if(!Number.isSafeInteger(result.uid)||result.uid<=0)throw new Error('Некорректный аккаунт.');
 await bindDeviceAccount(device,String(result.uid));check();
}
export async function loginDevice(device:Device,signal?:AbortSignal){
 await authenticateDevice(device,signal);return restoreSession();
}
export async function login(config:LoginConfig,signal?:AbortSignal){
 if(config.devices.length!==1)throw new Error(config.devices.length?'Выберите устройство для входа.':'На этом устройстве нет ключа. Откройте ссылку привязки.');
 return loginDevice(config.devices[0],signal);
}
