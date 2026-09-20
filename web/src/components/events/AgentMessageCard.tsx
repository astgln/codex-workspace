/* Adapted from LuSeptem/codex-webui; MIT notice in licenses/. */
import { useState, useCallback } from 'react';
import type { AgentMessageItem } from '@/types/api';
import { Copy, Check, MessageSquare } from 'lucide-react';
import { Markdown } from './Markdown';
import { formatItemTime } from '@/lib/utils/format';
import { useToast } from '@/stores/toast';

interface Props {
  item: AgentMessageItem;
  timestamp?: string;
  showHeader?: boolean;
}

export function AgentMessageCard({ item, timestamp, showHeader = true }: Props) {
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();
  const copy = useCallback(() => {
    navigator.clipboard.writeText(item.text ?? '').then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
      toast({ title: 'Скопировано', description: 'Ответ скопирован в буфер обмена', type: 'success', duration: 2000 });
    }).catch(() => {
      toast({ title: 'Не удалось скопировать', description: 'Выделите текст вручную', type: 'error', duration: 3000 });
    });
  }, [item.text, toast]);

  return <div className="assistant-message">
    <div className="assistant-message-heading">
      {showHeader && <span className="assistant-message-author"><MessageSquare size={14} aria-hidden="true"/>Codex</span>}
      {timestamp && <time dateTime={timestamp} title={new Date(timestamp).toString()}>{formatItemTime(timestamp)}</time>}
      <button className="assistant-copy" onClick={copy} title={copied ? 'Скопировано' : 'Копировать ответ'} aria-label={copied ? 'Скопировано' : 'Копировать ответ'}>
        {copied ? <Check size={14}/> : <Copy size={14}/>}
      </button>
    </div>
    <Markdown className="assistant-message-text">{item.text}</Markdown>
  </div>;
}
