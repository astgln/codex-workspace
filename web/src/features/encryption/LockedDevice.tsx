import {useState} from 'react';
import {parsePairingFragment} from './pairing';

export function LockedDevice({workspace,pair,logout}:{workspace:string;pair:(fragment:string)=>void;logout:()=>void}){
 const [link,setLink]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 async function submit(){
  setBusy(true);setError('');
  try{
   if(link.length>8192)throw new Error();
   const url=new URL(link.trim());
   if(url.origin!==location.origin||url.username||url.password||url.pathname!=='/'||url.search)throw new Error();
   const invitation=await parsePairingFragment(url.hash);
   if(invitation.workspace!==workspace)throw new Error();
   setLink('');pair(url.hash);
  }catch{setLink('');setError('Ссылка недействительна, истекла или выдана другому сайту. Создайте новую на доверенном устройстве.');}
  finally{setBusy(false);}
 }
 return <main className="login-page"><section className="login-card">
  <h1>Привяжите это приложение</h1>
  <p>В этом приложении нет ключа переписки. Safari и приложение с домашнего экрана хранят ключи отдельно.</p>
  <p>На доверенном устройстве создайте новую ссылку в разделе «Сквозное шифрование» и вставьте её здесь. Не открывайте её в другом браузере.</p>
  <form onSubmit={event=>{event.preventDefault();void submit();}}>
   <label htmlFor="device-invitation">Ссылка привязки</label>
   <input id="device-invitation" type="password" autoComplete="off" spellCheck={false} autoCapitalize="none" value={link} onChange={event=>setLink(event.target.value)} style={{width:'100%'}}/>
   <button className="primary login-button" disabled={busy||!link.trim()} type="submit">Продолжить привязку</button>
  </form>
  {error&&<p role="alert">{error}</p>}
  <p className="small muted">Ключи сохраняются отдельно на каждом устройстве.</p>
  <button className="quiet" onClick={logout}>Выйти</button>
 </section></main>;
}
