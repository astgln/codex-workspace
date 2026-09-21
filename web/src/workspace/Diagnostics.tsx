import { useState } from 'react';
import { request } from '../api/transport';

type Status = {
  collector_recent:boolean; collector_seen:number|null; history_synced:number|null;
  queue:Record<string,number>; completed:number;
  worker?:{status:string;observed_at:number;waiting:Record<string,number>;unresolved:number}|null;
  notifications:{devices:number;retrying:number;uncertain:number};
};
const date = (value:number|null) => value ? new Date(value*1000).toLocaleString('ru-RU') : 'нет данных';

export function Diagnostics(){
  const [status,setStatus]=useState<Status|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const refresh=async()=>{
    setBusy(true);setError('');
    try{setStatus(await request<Status>('/web/diagnostics',{}));}
    catch(error){setError(error instanceof Error?error.message:'Диагностика недоступна.');}
    finally{setBusy(false);}
  };
  return <details className="push-settings small" onToggle={event=>{if(event.currentTarget.open&&!status&&!busy)void refresh();}}>
    <summary>Состояние сервиса</summary>
    {status&&<>
      <p>{status.collector_recent?'Обработчик на связи':'Связь с обработчиком давно не обновлялась'}</p>
      <p className="muted">Связь: {date(status.collector_seen)}<br/>История: {date(status.history_synced)}</p>
      <p>На одобрение: {status.queue.awaiting_approval} · В очереди: {status.queue.approved}<br/>Готовых ответов: {status.completed}</p>
      {status.worker&&<div>
        <p className="muted">Последний проход: {date(status.worker.observed_at)}. Во время выполнения запроса эти данные могут не обновляться.</p>
        <p>Занятых задач: {status.worker.waiting.desktop_writer_lock}<br/>Нет сохранённых настроек: {status.worker.waiting.task_settings_unavailable}<br/>Требуют сверки: {status.worker.unresolved}</p>
        {status.worker.waiting.task_settings_unavailable>0&&<p className="muted">Продолжите эти задачи в desktop, чтобы сохранить актуальные настройки. Обработчик не расширяет их права.</p>}
        {status.worker.unresolved>0&&<p className="muted">Проверьте исходные задачи: результат запуска пока не подтверждён. Повторная отправка автоматически не выполняется.</p>}
      </div>}
      <p>Устройств с push: {status.notifications.devices}<br/>Повторных попыток в ожидании: {status.notifications.retrying}<br/>Неизвестный результат: {status.notifications.uncertain}</p>
      {status.notifications.uncertain>0&&<p className="muted">Неопределённые отправки не повторяются автоматически. Ответы доступны в переписке.</p>}
    </>}
    <button className="quiet" disabled={busy} onClick={()=>void refresh()}>{busy?'Проверяем…':'Обновить состояние'}</button>
    {error&&<p role="alert">{error}</p>}
  </details>;
}
