import {useState} from 'react';
import {MessageSquare} from 'lucide-react';
import {parsePairingFragment} from '../encryption/pairing';
type Props={checking:boolean;ready:boolean;busy:boolean;preparing:boolean;error:string;enter:(deviceId?:string)=>void;devices?:{deviceStamp:string;account:string}[];cancel:()=>void;prepare:()=>void;pair:(fragment:string)=>void};
export function LoginPage({checking,ready,busy,preparing,error,enter,cancel,prepare,pair,devices=[]}:Props){
 const [selected,setSelected]=useState('');
 const [link,setLink]=useState(''),[pairError,setPairError]=useState('');
 const connect=async()=>{try{const url=new URL(link.trim());if(url.origin!==location.origin)throw new Error();await parsePairingFragment(url.hash);setLink('');pair(url.hash);}catch{setLink('');setPairError('Ссылка недействительна или истекла. Создайте новую на доверенном устройстве.');}};
 return <main className="login-page"><section className="login-card"><div className="brand-mark"><MessageSquare size={26}/></div><p className="eyebrow">CODEX WORKSPACE</p><h1>Ваши задачи Codex.<br/>В одном окне.</h1>
 <p className="muted">Вход с ключом этого устройства. Закрытый ключ остаётся в браузере.</p>
 {devices.length>1&&<label>Аккаунт устройства<select value={selected||devices[0].deviceStamp} onChange={event=>setSelected(event.target.value)}>{devices.map(d=><option key={d.deviceStamp} value={d.deviceStamp}>Аккаунт {d.account} · {d.deviceStamp.slice(0,8)}</option>)}</select></label>}
 <button className="primary login-button" disabled={checking||!ready||busy} onClick={()=>enter(selected||devices[0]?.deviceStamp)}>{checking?'Проверяем сессию…':busy?'Проверяем ключ…':preparing?'Читаем ключ устройства…':'Войти с ключом устройства'}</button>
 {busy&&<button className="quiet" onClick={cancel}>Отменить вход</button>}
 {error&&<div role="alert">{error}<button onClick={prepare}>Повторить</button></div>}
 <details><summary>Новое устройство</summary><p>Создайте приглашение на доверенном устройстве и вставьте ссылку здесь.</p>
 <form onSubmit={event=>{event.preventDefault();void connect();}}><label htmlFor="login-pair-link">Ссылка привязки</label><input id="login-pair-link" type="password" autoComplete="off" spellCheck={false} value={link} onChange={e=>setLink(e.target.value)}/><button disabled={!link.trim()} type="submit">Продолжить привязку</button></form>{pairError&&<p role="alert">{pairError}</p>}</details>
 <details><summary>Восстановление доступа</summary><p>На компьютере с локальным обработчиком восстановите сохранённый пакет с ключом восстановления через команду devices restore, затем создайте новое приглашение. Не отправляйте ключ или пакет на сервер.</p></details>
 </section></main>;
}
