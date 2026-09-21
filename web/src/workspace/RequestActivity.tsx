import type { Message } from '../api';

export function RequestActivity({message, online}:{message:Message; online:boolean}) {
  if (['completed', 'failed', 'needs_input'].includes(message.result_status || '')) return null;
  if (!['awaiting_approval', 'approved', 'delivered'].includes(message.status)) return null;
  const text = message.status === 'awaiting_approval' ? 'Ожидаю одобрения…'
    : !online ? 'Ожидаю подключения Codex…'
    : message.result_status === 'running' ? 'Думаю…'
    : message.status === 'approved' ? 'В очереди Codex…'
    : 'Ожидаю ответа Codex…';
  return <div className="request-activity" role="status" aria-live="polite">
    <span className="request-activity-text">{text}</span>
  </div>;
}
