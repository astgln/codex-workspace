import {useEffect, useRef, useState} from 'react';
import {createPairingOffer, openPairingGrant, parsePairingFragment} from './pairing';
import {getOrCreateDevice, installBundle, loadDevice} from './vault';
import {request} from '../../shared/api/transport';
import type {Envelope} from './envelope';

/** Clear the bearer fragment before mounting any application or login effect. */
export function consumePairingFragment(): string {
  const fragment = window.location.hash;
  if (!fragment.startsWith('#pair=')) return '';
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
  return fragment;
}

export function PairingScreen({account, fragment, close}: {account:string; fragment:string; close:()=>void}) {
  const [status,setStatus] = useState<'ready'|'waiting'|'done'|'error'>('ready');
  const active = useRef(0);
  const pending = useRef<ReturnType<typeof createPairingOffer> | null>(null);
  useEffect(()=>()=>{active.current++;pending.current=null;},[]);
  const connect = async()=>{
    const run = ++active.current;
    setStatus('waiting');
    // Best effort: denial must not prevent enrollment or claim persistence.
    void navigator.storage?.persist?.().catch(()=>false);
    try {
      const invitation = await parsePairingFragment(fragment);
      const device = await getOrCreateDevice(account, invitation.workspace);
      if (active.current !== run) return;
      // Preserve the exact offer across network retries; never replace a mailbox entry.
      pending.current ??= createPairingOffer(invitation, device.signing);
      const offer = await pending.current;
      if (active.current !== run) return;
      await request('/web/e2ee/pairing/offer', {workspace:invitation.workspace, ...offer});
      while (active.current === run && Date.now()/1000 < invitation.expires) {
        const reply = await request<{payload:{envelope:Envelope}|null}>('/web/e2ee/pairing/read',
          {workspace:invitation.workspace,id:invitation.id});
        if (active.current !== run) return;
        if (reply.payload) {
          const bundle = await openPairingGrant(invitation, reply.payload.envelope, device.signing.publicKey, location.origin);
          if (active.current !== run) return;
          await installBundle(account,bundle,{workspace:invitation.workspace,origin:location.origin,authority:invitation.authority});
          const saved=await loadDevice(account,invitation.workspace);
          if(!saved?.bundle||saved.deviceStamp!==device.deviceStamp||JSON.stringify(saved.bundle)!==JSON.stringify(bundle))throw new Error('Key storage verification failed');
          if (active.current === run) {pending.current=null;setStatus('done');}
          return;
        }
        await new Promise(resolve=>setTimeout(resolve,2000));
      }
      if (active.current === run) setStatus('error');
    } catch {
      // Never expose raw API responses, URLs, keys or the invitation in diagnostics.
      if (active.current === run) setStatus('error');
    }
  };
  return <main className="login-page"><section className="login-card" aria-label="Привязка устройства">
    <h1>Привязать устройство</h1>
    <p className="muted">Открывайте приглашение только со своего доверенного устройства. Вход через Telegram сам по себе не даёт ключей.</p>
    <p role="status" className="small muted">{status==='waiting'?'Ожидаем подтверждение локального обработчика…':status==='done'?'Ключи проверены и сохранены на этом устройстве.':status==='error'?'Не удалось завершить привязку. Проверьте связь и срок приглашения.':''}</p>
    {status!=='done'&&<button className="primary login-button" disabled={status==='waiting'} onClick={()=>void connect()}>{status==='error'?'Повторить':'Привязать'}</button>}
    <button className="quiet" onClick={()=>{active.current++;pending.current=null;close();}}>{status==='done'?'Закрыть':'Отмена'}</button>
    <p className="small muted">Ключи сохраняются в этом приложении или браузере. Для Safari и PWA нужна отдельная привязка.</p>
  </section></main>;
}
