import { ArrowUp, Paperclip, Plus, X } from 'lucide-react';
import type { Thread } from '../api';
import type { useComposer } from './useComposer';

type Props = {
 composer: ReturnType<typeof useComposer>;
 selected: string;
 thread: Thread;
 busy: boolean;
};

export function Composer({composer,selected,thread,busy}:Props){
 const {drafts,setDrafts,attachments,setAttachments,uploading,fileInput,attach,send}=composer;
 return <div className="composer-wrap"><div className="composer content-width">{attachments[selected]?.map(file=><div className="attachment-card" key={file.id}><Paperclip size={14}/><span>{file.name}</span><button className="icon-button" aria-label={"Убрать "+file.name} disabled={busy} onClick={()=>setAttachments(a=>({...a,[selected]:a[selected].filter(f=>f.id!==file.id)}))}><X size={14}/></button></div>)}{uploading&&<p className="small muted" role="status">Загрузка: {uploading}</p>}<textarea disabled={busy} aria-label="Сообщение" placeholder="Спросите что-нибудь…" value={drafts[selected]||''} maxLength={16000} onChange={e=>setDrafts(d=>({...d,[selected]:e.target.value}))} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();void send();}}}/><div className="composer-bottom"><input ref={fileInput} type="file" multiple hidden onChange={e=>void attach(e.target.files)}/><button className="icon-button" aria-label="Прикрепить файлы" disabled={busy||(attachments[selected]?.length||0)>=4} onClick={()=>fileInput.current?.click()}><Plus size={22}/></button><button className="send-button" disabled={busy||(!drafts[selected]?.trim()&&!attachments[selected]?.length)} onClick={()=>void send()} aria-label="Отправить"><ArrowUp size={19}/></button></div></div><p className="composer-note">{thread.title} · Ctrl / ⌘ + Enter — отправить</p></div>;
}
