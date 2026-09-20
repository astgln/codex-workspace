import {useEffect,useState} from 'react';
import {pushConfig,pushSubscribe,pushUnsubscribe} from './api';
const standalone=()=>matchMedia('(display-mode: standalone)').matches || Boolean((navigator as Navigator & {standalone?:boolean}).standalone);
export async function disablePush(){
 if(!('serviceWorker' in navigator))return;
 const registration=await navigator.serviceWorker.getRegistration('/');
 const subscription=await registration?.pushManager.getSubscription();
 if(subscription){await pushUnsubscribe(subscription.toJSON());await subscription.unsubscribe();}
}
export function PushSettings(){
 const [enabled,setEnabled]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [key,setKey]=useState('');
 const supported='serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
 const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
 useEffect(()=>{
  if(!supported)return;
  let active=true;
  Promise.all([navigator.serviceWorker.register('/sw.js',{scope:'/',updateViaCache:'none'}),pushConfig()]).then(async([registration,config])=>{
   const subscription=await registration.pushManager.getSubscription();
   if(subscription)await pushSubscribe(subscription.toJSON());
   if(active){setKey(config.public_key);setEnabled(Boolean(subscription));}
  }).catch(()=>{if(active)setError('Не удалось настроить уведомления. Обновите страницу.');});
  return()=>{active=false;};
 },[supported]);
 const toggle=async()=>{
  setBusy(true);setError('');
  try{
   if(enabled){await disablePush();setEnabled(false);return;}
   // The permission request must occur directly in the user's click on iOS.
   if(await Notification.requestPermission()!=='granted')throw new Error('Уведомления не разрешены. Проверьте настройки уведомлений этого приложения.');
   const registration=await navigator.serviceWorker.ready;
   const bytes=Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
   const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
   try{await pushSubscribe(subscription.toJSON());}catch(error){await subscription.unsubscribe();throw error;}
   setEnabled(true);
  }catch(error){setError(error instanceof Error?error.message:'Не удалось включить уведомления.');}
  finally{setBusy(false);}
 };
 return <details className="push-settings small"><summary>Приложение и уведомления</summary>{!standalone()&&<p className="muted">{ios?'На iPhone: Safari → Поделиться → На экран «Домой». Затем откройте приложение с его значка.':'Сайт можно установить через меню браузера «Установить приложение».'}</p>}{ios&&!standalone()?<p className="muted">Push доступны в установленном приложении на iOS 16.4 и новее.</p>:supported?<button className="quiet" disabled={busy||!key} onClick={()=>void toggle()}>{enabled?'Выключить уведомления':'Включить уведомления'}</button>:<p className="muted">Этот браузер не поддерживает push-уведомления.</p>}<p className="muted">Готовые ответы и запросы на одобрение. Текст переписки скрыт.</p>{error&&<p role="alert">{error}</p>}</details>;
}
