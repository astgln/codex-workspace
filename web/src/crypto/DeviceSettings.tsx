import {useEffect,useRef,useState} from 'react';
import {createDeviceInvitation} from './client';
export function DeviceSettings(){
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
  setBusy(true);setError('');setInvitation(null);
  try{const value=await createDeviceInvitation();if(active.current)setInvitation(value);}
  catch{if(active.current)setError('Не удалось создать ссылку. Проверьте, что ноутбук на связи.');}
  finally{if(active.current)setBusy(false);}
 }
 return <details className="small"><summary>Сквозное шифрование</summary>
  <p className="muted">Это устройство хранит ключи переписки.</p>
  <button className="quiet" disabled={busy} onClick={()=>void invite()}>{busy?'Создаём приглашение…':'Привязать ещё устройство'}</button>
  {invitation&&<><p>Ссылка даёт доступ к вашей переписке. Передайте её только своему устройству; она действует 10 минут.</p>
   <button className="quiet" onClick={()=>void navigator.clipboard.writeText(invitation.link).catch(()=>setError('Не удалось скопировать ссылку.'))}>Скопировать ссылку</button>
   <button className="quiet" onClick={()=>setInvitation(null)}>Скрыть ссылку</button></>}
  {error&&<p role="alert">{error}</p>}
 </details>;
}
