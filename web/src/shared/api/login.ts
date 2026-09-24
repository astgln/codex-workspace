import { request, restoreSession } from './transport';
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
