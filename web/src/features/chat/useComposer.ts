import { useEffect, useRef, useState } from 'react';
import { sendMessage, uploadFile, type Attachment } from '../../shared/api/index';

type Options = {
  selected: string;
  sessionVersion: number;
  busy: boolean;
  setBusy: (value: boolean) => void;
  setError: (value: string) => void;
  action: (operation: () => Promise<unknown>) => Promise<void>;
};
type Submission = { thread: string; text: string; id: string; files: string[] };

// Capture a target at submission/upload start; navigation never retargets work.
export function useComposer({ selected, sessionVersion, busy, setBusy, setError, action }: Options) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [attachments, setAttachments] = useState<Record<string, Attachment[]>>({});
  const [uploading, setUploading] = useState('');
  const [sending, setSending] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const submission = useRef<Submission | null>(null);

  const session = useRef(sessionVersion);
  session.current = sessionVersion;
  useEffect(() => {
    setDrafts({}); setAttachments({}); setUploading(''); setSending('');
    submission.current = null;
  }, [sessionVersion]);

  const attach = async (files: FileList | null) => {
    if (!files || !selected || busy) return;
    const target = selected;
    const version = session.current;
    const ensureActive = () => {
      if (version !== session.current) throw new DOMException('Session changed', 'AbortError');
    };
    const pending = Array.from(files);
    if ((attachments[target]?.length || 0) + pending.length > 4) {
      setError('Можно прикрепить до четырёх файлов.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      for (const file of pending) {
        ensureActive();
        setUploading(file.name);
        const result = await uploadFile(target, file, percent => {
          ensureActive(); setUploading(`${file.name} · ${percent}%`);
        }, ensureActive);
        ensureActive();
        setAttachments(current => ({ ...current, [target]: [...(current[target] || []), result] }));
      }
    } catch (error) {
      if (version === session.current) setError(error instanceof Error ? error.message : 'Не удалось загрузить файл.');
    } finally {
      if (version === session.current) {
        setUploading(''); setBusy(false);
        if (fileInput.current) fileInput.current.value = '';
      }
    }
  };

  const send = async () => {
    const text = (drafts[selected] || '').trim();
    const files = (attachments[selected] || []).map(file => file.id);
    if (busy || !selected || (!text && !files.length)) return;
    const target = selected;
    const previous = submission.current;
    // Retries of the same payload keep the same idempotency key.
    if (!previous || previous.thread !== target || previous.text !== text ||
        JSON.stringify(previous.files) !== JSON.stringify(files)) {
      submission.current = { thread: target, text, id: crypto.randomUUID(), files };
    }
    const current = submission.current!;
    const version = session.current;
    setSending(target);
    try {
      await action(async () => {
        await sendMessage(current.thread, current.text, current.id, current.files);
        if (version !== session.current) return;
        setDrafts(value => ({ ...value, [target]: '' }));
        setAttachments(value => ({ ...value, [target]: [] }));
        submission.current = null;
      });
    } finally {
      if (version === session.current) setSending('');
    }
  };

  return { drafts, setDrafts, attachments, setAttachments, uploading, sending, fileInput, submission, attach, send };
}
