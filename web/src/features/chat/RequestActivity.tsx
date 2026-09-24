import type {Message} from '../../shared/api/types';
import {requestStatus} from '../../shared/api/requestStatus';

export function RequestActivity({message,online}:{message:Message;online:boolean}){
 const state=requestStatus(message.result_status||message.status);
 if(!state.activity)return null;
 return <div className="request-activity" role="status" aria-live="polite">
  <span className="request-activity-text">{online?state.activity:'Ожидаю подключения Codex…'}</span>
 </div>;
}
