import {requestStatus} from '../../shared/api/requestStatus';
import { Check, Download, Folder, MessageSquare } from 'lucide-react';
import { Markdown } from '../../shared/components/events/Markdown';
import { decide, downloadFile } from '../../shared/api/index';
import type { WorkspaceState, Thread } from '../../shared/api/index';
import type { FileChangeItem } from '../../shared/types/api';
import type { useThreadHistory } from './History';
import { PublicEvent } from './PublicEvent';
import { RequestActivity } from './RequestActivity';


type Props = {
 state: WorkspaceState;
 section: 'threads' | 'approvals';
 selected: string;
 thread?: Thread;
 history: ReturnType<typeof useThreadHistory>;
 busy: boolean;
 online: boolean;
 action: (fn: () => Promise<unknown>) => Promise<void>;
 setDiff: (item: FileChangeItem) => void;
};

export function Conversation({state, section, selected, thread, history, busy, online, action, setDiff}: Props) {
 const owner = state.user.role === 'owner';
 const direct = owner || state.user.requires_approval === false;
 const messages = state.messages.filter(message => section === 'approvals' ? message.status === 'awaiting_approval' : message.thread === selected)
  .sort((a,b) => a.created-b.created || b.id-a.id);
 const timeline = [...messages.map(value => ({kind:'request' as const,value})),
  ...(section === 'threads' ? (history.page?.messages || []).map(value => ({kind:'history' as const,value})) : [])]
  .sort((a,b) => a.value.created-b.value.created);
 return (
<div className="content-width conversation">{section==='threads'&&<><div className="small muted" role="status">{history.page?.synced_at?history.page.loading_older?'Загружаем прежнюю переписку…':'Общая история задачи':'Ожидаем историю из Codex…'}</div>{history.error&&<div className="error-box">{history.error}<button onClick={()=>void history.refresh()}>Повторить загрузку истории</button></div>}{history.page?.before&&<button className="quiet" disabled={history.busy} onClick={()=>void history.refresh(history.page!.before!)}>Показать более ранние сообщения</button>}</>}{timeline.length===0?<div className="empty-conversation"><MessageSquare size={32}/><h1>{section==='approvals'?'Все запросы разобраны':thread?'Начните разговор':'Выберите тред'}</h1><p className="muted">{section==='approvals'?'Новые сообщения появятся здесь для проверки.':thread?(direct?'Опишите результат теста или задайте вопрос. Запрос сразу попадёт в очередь Codex.':'Опишите результат теста или задайте вопрос. Владелец проверит запрос перед передачей в Codex.'):'Здесь появятся сообщения, отправленные через это рабочее пространство.'}</p></div>:timeline.map(entry=>entry.kind==='history'?<article className="bridge-turn" data-scroll-id={"history:"+entry.value.id} key={"history:"+entry.value.id}><div className="message-meta"><span>{entry.value.role==='assistant'?'Codex':'Участник'}</span><time>{new Date(entry.value.created*1000).toLocaleString('ru-RU')}</time></div><div className={entry.value.role==='user'?'user-bubble':'response-stream'}><Markdown>{entry.value.text}</Markdown></div></article>:(()=>{const message=entry.value;return <article className="bridge-turn" data-scroll-id={"request:"+message.id} key={"request:"+message.id}>
       {section==='approvals'&&<div className="approval-destination"><Folder size={14}/>{state.threads.find(t=>t.id===message.thread)?.title||'Тред недоступен'}</div>}
       <div className="message-meta"><span>{message.sender===state.user.id?'Вы':`Участник ${message.sender}`}</span><time>{new Date(message.created*1000).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}</time></div>
       <div className="user-bubble"><Markdown>{message.text}</Markdown>{message.attachments?.map(file=><button key={file.id} className="attachment-card" disabled={busy} onClick={()=>void action(()=>downloadFile(file))}><Download size={15}/><span>{file.name}</span><small>{Math.ceil(file.size/1024)} КБ</small></button>)}</div>
       <div className={'delivery-status status-'+message.status}><span>{requestStatus(message.result_status||message.status).label}</span>{owner&&message.status==='awaiting_approval'&&<div className="decision-buttons"><button disabled={busy} className="quiet" onClick={()=>void action(()=>decide(message,'rejected'))}>Отклонить</button><button disabled={busy} className="approve" onClick={()=>void action(()=>decide(message,'approved'))}><Check size={14}/>Передать в Codex</button></div>}</div>
       <div className="response-stream">{message.events?.map((event,index)=><PublicEvent key={event.id||index} event={event} openDiff={setDiff}/>)}{section==='threads'&&<RequestActivity message={message} online={online}/>}</div>
      </article>;})())}</div>
 );
}
