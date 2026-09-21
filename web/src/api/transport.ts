import type { WorkspaceState } from './types';
let csrfToken = '';
export async function signOut(){await request('/auth/logout',{});csrfToken='';}
export async function restoreSession(){const value=await request<{csrf:string;workspace:WorkspaceState}>('/auth/session');csrfToken=value.csrf;return value.workspace;}
export class ApiError extends Error { constructor(public status:number,message:string){super(message);} }
export async function request<T>(path:string,body?:unknown):Promise<T>{
  const r = await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(csrfToken?{'X-CSRF-Token':csrfToken}:{})},body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(15000)}).catch((error:unknown)=>{if(error instanceof DOMException&&(error.name==='TimeoutError'||error.name==='AbortError'))throw new Error('Сервер не ответил за 15 секунд. Повторите попытку.');throw error;});
  if(!r.ok){ if(r.status===401)csrfToken=''; throw new ApiError(r.status,r.status===401?'Сессия истекла. Войдите снова.':r.status===403?'Нет доступа к этому действию.':r.status===429?'Слишком много попыток. Подождите немного и повторите вход.':r.status===409?'Запрос уже изменился или недоступен. Обновите страницу.':'Сервис временно недоступен. Попробуйте снова.'); }
  return r.json();
}
