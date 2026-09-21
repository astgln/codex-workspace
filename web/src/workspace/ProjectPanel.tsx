import { ChevronRight, MessageSquare } from 'lucide-react';
import type { Thread } from '../api';

type Props = {
 activeProject?: {id:string;title:string};
 projectThreads: Thread[];
 search: string;
 setSearch: (value:string)=>void;
 choose: (id:string)=>void;
};

export function ProjectPanel({activeProject,projectThreads,search,setSearch,choose}:Props){
 return <div className="content-width project-panel"><h1>{activeProject?.title||'Проекты'}</h1><p className="muted">Задачи проекта</p><input className="thread-search" placeholder="Найти задачу…" aria-label="Найти задачу проекта" value={search} onChange={e=>setSearch(e.target.value)}/><nav aria-label="Задачи проекта">{projectThreads.filter(t=>t.title.toLowerCase().includes(search.toLowerCase())).map(t=><button key={t.id} className="thread-row" onClick={()=>choose(t.id)}><MessageSquare size={17}/><span>{t.title}</span>{t.status==='active'&&<span className="activity-dot" title="Активная задача"/>}<ChevronRight size={16}/></button>)}</nav>{!projectThreads.some(t=>t.title.toLowerCase().includes(search.toLowerCase()))&&<p className="empty-note muted">{search?'Задачи не найдены.':'Список задач появится после синхронизации с Codex.'}</p>}</div>;
}
