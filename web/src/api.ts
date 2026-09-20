import type { ResponseItem } from './types/api';
export type Thread = { id:string; title:string; status:string; read_only?:boolean };
export type Attachment = {id:string;name:string;size:number;sha256:string};
export type Message = { id:number; sender:number; thread:string; text:string; created:number; expires:number; status:string; snapshot:string; events?:ResponseItem[]; result_status?:string; attachments?:Attachment[] };
export type WorkspaceState = {weekly_quota?:{used_percent:number;resets_at:number;observed_at:number}|null;user:{id:number;role:'owner'|'member';requires_approval?:boolean};threads:Thread[];messages:Message[];members?:{id:number;username:string;requires_approval?:boolean;threads:string[]}[];catalog_updated:number|null;collector_seen:number|null};
let csrfToken = '';
export async function signOut(){await request('/auth/logout',{});csrfToken='';}
export async function restoreSession(){const value=await request<{csrf:string;workspace:WorkspaceState}>('/auth/session');csrfToken=value.csrf;return value.workspace;}
export class ApiError extends Error { constructor(public status:number,message:string){super(message);} }
async function request<T>(path:string,body?:unknown):Promise<T>{
  const r = await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(csrfToken?{'X-CSRF-Token':csrfToken}:{})},body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(15000)}).catch((error:unknown)=>{if(error instanceof DOMException&&(error.name==='TimeoutError'||error.name==='AbortError'))throw new Error('Сервер не ответил за 15 секунд. Повторите попытку.');throw error;});
  if(!r.ok){ if(r.status===401)csrfToken=''; throw new ApiError(r.status,r.status===401?'Сессия истекла. Войдите снова.':r.status===403?'Нет доступа к этому действию.':r.status===409?'Запрос уже изменился или недоступен. Обновите страницу.':'Сервис временно недоступен. Попробуйте снова.'); }
  return r.json();
}
type LoginConfig = {client_id:string;nonce:string;challenge:string};
const TELEGRAM_ORIGIN='https://oauth.telegram.org';
export const prepareLogin=()=>request<LoginConfig>('/web/login/config');

// Telegram's post_message flow, with explicit origin for the authorization endpoint.
// The current official JS library omits origin; the live endpoint rejects that URL.
// Signed ID tokens and Login Widget objects are verified by the server;
// browser profile claims never establish identity.
export function login(config:LoginConfig,signal?:AbortSignal):Promise<void>{
  return new Promise((resolve,reject)=>{
    let finished=false,verifying=false,popup:Window|null=null;
    const finish=(error?:unknown)=>{
      if(finished)return;finished=true;
      clearTimeout(timer);clearInterval(closedTimer);
      window.removeEventListener('message',receive);signal?.removeEventListener('abort',cancel);
      popup?.close();
      if(error)reject(error);else resolve();
    };
    const cancel=()=>finish(new Error('Вход отменён. Можно попробовать снова.'));
    const receive=async(event:MessageEvent)=>{
      if(finished||verifying||event.origin!==TELEGRAM_ORIGIN||event.source!==popup||!popup)return;
      let data:unknown=event.data;
      if(typeof data==='string'){try{data=JSON.parse(data);}catch{return;}}
      if(!data||typeof data!=='object'||!('event' in data)||data.event!=='auth_result')return;
      const payload='result' in data?data.result:undefined;
      const widget=payload!==null&&typeof payload==='object'&&!Array.isArray(payload)&&'hash' in payload&&'auth_date' in payload&&'id' in payload;
      if((typeof payload!=='string'&&!widget)||('error' in data&&data.error)){
        const allowed=['result','error','id_token','auth_data','id','first_name','last_name','username','photo_url','auth_date','hash'];
        const keys=(value:object)=>Object.keys(value).filter(key=>allowed.includes(key)).sort().join(',')||'none';
        const result='result' in data?data.result:undefined;
        const shape=result===null?'null':typeof result;
        const fields=result&&typeof result==='object'?keys(result):'none';
        finish(new Error(`Telegram вернул неожиданный формат: fields=${keys(data)}; result=${shape}; result_fields=${fields}. Значения и токены скрыты.`));return;
      }
      verifying=true;
      try{
        await request<{ok:boolean}>('/web/login/session',{...(widget?{widget_data:payload}:{id_token:payload}),challenge:config.challenge});
        if(finished)return;await restoreSession();if(finished)return;finish();
      }catch(error){finish(error);}
    };
    const timer=setTimeout(()=>finish(new Error('Нет ответа от окна Telegram. Разрешите всплывающее окно или откройте сайт в обычном браузере.')),120000);
    const closedTimer=setInterval(()=>{if(popup?.closed&&!verifying)cancel();},300);
    signal?.addEventListener('abort',cancel,{once:true});
    if(signal?.aborted){cancel();return;}
    const url=new URL('/auth',TELEGRAM_ORIGIN);
    url.search=new URLSearchParams({response_type:'post_message',client_id:config.client_id,
      redirect_uri:location.origin+location.pathname,origin:location.origin,
      scope:'openid profile',nonce:config.nonce,lang:'ru'}).toString();
    window.addEventListener('message',receive);
    try{
      popup=window.open(url.toString(),'telegram_workspace_login','popup,width=550,height=650');
      if(!popup){finish(new Error('Браузер заблокировал окно Telegram. Разрешите всплывающие окна для этого сайта или откройте его в обычном браузере.'));return;}
      popup.focus();
    }catch{finish(new Error('Не удалось открыть окно Telegram. Попробуйте обычный браузер.'));}
  });
}
export const fetchState=()=>request<WorkspaceState>('/web/state',{});
export const sendMessage=(thread:string,text:string,request_id:string,attachments:string[]=[])=>request<Message>('/web/messages',{thread,text,request_id,attachments});
export const decide=(message:Message,decision:'approved'|'rejected')=>request<Message>('/web/decisions',{id:message.id,snapshot:message.snapshot,decision});
export const grant=(user_id:number,threads:string[])=>request('/web/grants',{user_id,threads});

async function sha256(bytes:Uint8Array){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes as BufferSource))).map(b=>b.toString(16).padStart(2,'0')).join('');}
export async function uploadFile(thread:string,file:File,onProgress:(percent:number)=>void):Promise<Attachment>{
  if(!file.size||file.size>5*1024*1024)throw new Error('Размер файла должен быть от 1 байта до 5 МБ.');
  const bytes=new Uint8Array(await file.arrayBuffer());
  const upload=await request<Attachment&{chunk_size:number}>('/web/uploads/start',{thread,name:file.name,size:file.size,sha256:await sha256(bytes),request_id:crypto.randomUUID()});
  for(let offset=0,index=0;offset<bytes.length;offset+=upload.chunk_size,index++){
    const part=bytes.slice(offset,offset+upload.chunk_size);
    const data=btoa(String.fromCharCode(...part));
    await request('/web/uploads/chunk',{id:upload.id,index,data});
    onProgress(Math.round(Math.min(offset+part.length,bytes.length)/bytes.length*100));
  }
  return request<Attachment>('/web/uploads/finish',{id:upload.id});
}
export async function downloadFile(file:Attachment){
  const bytes=new Uint8Array(file.size);
  for(let offset=0,index=0;offset<bytes.length;index++){
    const part=await request<{data:string;chunk_size:number}>('/web/uploads/get',{id:file.id,index});
    const chunk=Uint8Array.from(atob(part.data),c=>c.charCodeAt(0));
    if(!chunk.length||offset+chunk.length>bytes.length)throw new Error('Некорректный файл.');
    bytes.set(chunk,offset);offset+=chunk.length;
  }
  if(await sha256(bytes)!==file.sha256)throw new Error('Контрольная сумма файла не совпала.');
  const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download=file.name;anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),30000);
}

export type HistoryMessage={id:string;position:string;role:'user'|'assistant';text:string;created:number};
export type HistoryPage={messages:HistoryMessage[];before:string|null;synced_at:number|null;loading_older:boolean;pending:boolean};
export const fetchHistory=(thread:string,before?:string)=>request<HistoryPage>('/web/history',{thread,...(before?{before}:{})});

export const pushConfig=()=>request<{public_key:string}>('/web/push/config',{});
export const pushSubscribe=(subscription:PushSubscriptionJSON)=>request('/web/push/subscribe',{subscription});
export const pushUnsubscribe=(subscription:PushSubscriptionJSON)=>request('/web/push/unsubscribe',{subscription});

export const setMemberPolicy=(user_id:number,requires_approval:boolean)=>request('/web/member-policy',{user_id,requires_approval});
