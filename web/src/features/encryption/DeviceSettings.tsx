import {useEffect,useRef,useState} from 'react';
import {createDeviceInvitation} from './client';
export function DeviceSettings({userId}:{userId?:number}={}){
 const [elapsed,setElapsed]=useState(0);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const [invitation,setInvitation]=useState<{link:string;expires:number}|null>(null);
 const active=useRef(true);
 useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
 useEffect(()=>{
  if(!invitation)return;
  const timer=setTimeout(()=>setInvitation(null),Math.max(0,invitation.expires*1000-Date.now()));
  return()=>clearTimeout(timer);
 },[invitation]);
 async function invite(){
  setBusy(true);setElapsed(0);setError('');setInvitation(null);
  try{const value=await createDeviceInvitation(userId,seconds=>{if(active.current)setElapsed(seconds);});if(active.current)setInvitation(value);}
  catch{if(active.current)setError('Не получили приглашение. Проверьте связь с ноутбуком и повторите попытку — сохранённый запрос будет продолжен.');}
  finally{if(active.current)setBusy(false);}
 }
 return <details className="small"><summary>Сквозное шифрование</summary>
  <p className="muted">{userId?'Привяжите устройство участника к выданным ему задачам.':'Это устройство хранит ключи переписки.'}</p>
  <button className="quiet" disabled={busy} onClick={()=>void invite()}>{busy?'Ждём ноутбук…':userId?'Привязать устройство участника':'Привязать ещё устройство'}</button>
  {busy&&<p role="status">Запрос зашифрован. Ожидаем подтверждение ноутбука — {elapsed} с. Обычно это занимает несколько секунд. При задержке можно повторить попытку: запрос сохранён.</p>}
  {invitation&&<><p>{userId?'Передайте ссылку только этому участнику. Он получит ключи разрешённых ему задач.':'Передайте ссылку только своему устройству: она даёт доступ к вашей переписке.'} Ссылка действует 10 минут.</p>
   <button className="quiet" onClick={()=>void navigator.clipboard.writeText(invitation.link).catch(()=>setError('Не удалось скопировать ссылку.'))}>Скопировать ссылку</button>
   <button className="quiet" onClick={()=>setInvitation(null)}>Скрыть ссылку</button></>}
  {error&&<p role="alert">{error}</p>}
 </details>;
}
