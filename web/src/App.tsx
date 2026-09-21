/* Workspace shell adapted from LuSeptem/codex-webui AppShell; MIT notice in licenses/. */
import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Circle, Folder, Inbox, LogOut, Menu, MessageSquare, Moon, RefreshCw, ShieldCheck, Sun, X } from 'lucide-react';
import { DiffViewerDialog } from './components/diff/DiffViewerDialog';
import { useThreadHistory } from './History';
import { useConversationScroll } from './ConversationScroll';
import {PushSettings} from './PushSettings';
import { Toaster } from './components/ui/Toaster';
import type { FileChangeItem } from './types/api';
import { useWorkspaceSession } from './workspace/useWorkspaceSession';

import { AccessPanel } from './workspace/AccessPanel';
import { ProjectPanel } from './workspace/ProjectPanel';
import { Diagnostics } from './workspace/Diagnostics';
import { Composer } from './workspace/Composer';
import { useComposer } from './workspace/useComposer';
import { LoginPage } from './workspace/LoginPage';
import { Conversation } from './workspace/Conversation';

export function App(){
 const {state,checking,busy,setBusy,error,setError,resetVersion,config,preparing,prepare,refresh,action,enter,logout,cancelLogin}=useWorkspaceSession();
 const [projectId,setProjectId]=useState('');
 const [projectExpanded,setProjectExpanded]=useState(true);
 const [selected,setSelected]=useState(''),[section,setSection]=useState<'threads'|'approvals'|'access'|'project'>('threads');
 const [sidebar,setSidebar]=useState(false),[search,setSearch]=useState('');
 const [diff,setDiff]=useState<FileChangeItem|null>(null);
 const [dark,setDark]=useState(()=>localStorage.getItem('workspace-theme')!=='light');
 useEffect(()=>{document.documentElement.classList.toggle('dark',dark);localStorage.setItem('workspace-theme',dark?'dark':'light');},[dark]);
 useEffect(()=>{
  if(!state)return;
  const follow=()=>{const hash=location.hash;if(hash==='#approvals'&&state.user.role==='owner')setSection('approvals');else if(hash.startsWith('#thread=')){const id=hash.slice(8);if(state.threads.some(t=>t.id===id)){setProjectId(state.threads.find(t=>t.id===id)?.project_id||'');setSelected(id);setSection('threads');}}};
  follow();window.addEventListener('hashchange',follow);return()=>window.removeEventListener('hashchange',follow);
 },[Boolean(state)]);
 const composer=useComposer({selected,busy,setBusy,setError,action});
 const {setDrafts,setAttachments,sending,submission}=composer;
 useEffect(()=>{setDrafts({});setAttachments({});submission.current=null;setSelected('');setSection('threads');},[resetVersion]);
 useEffect(()=>{if(state)setSelected(current=>state.threads.some(t=>t.id===current)?current:state.threads[0]?.id||'');},[state]);
 const history=useThreadHistory(selected,Boolean(state)&&section==='threads');
 const scroll=useConversationScroll(state&&section==='threads'?`${state.user.id}:${selected}`:'',Boolean(history.page),history.page?.before||null,before=>void history.refresh(before));
 if(!state)return <LoginPage checking={checking} ready={Boolean(config)} busy={busy} preparing={preparing} error={error} enter={enter} cancel={cancelLogin} prepare={prepare}/>;
 const owner=state.user.role==='owner';
 const direct=owner||state.user.requires_approval===false;
 const projects=state.projects||[{id:'legacy',title:'Warcraft'}];
 const activeProject=projects.find(p=>p.id===projectId)||projects.find(p=>p.id===state.threads.find(t=>t.id===selected)?.project_id)||projects[0];
 const projectThreads=state.threads.filter(t=>!t.project_id||t.project_id===activeProject?.id);
 const thread=state.threads.find(t=>t.id===selected);
 const waiting=state.messages.filter(m=>m.status==='awaiting_approval');
 const online=state.collector_seen!==null&&Date.now()/1000-state.collector_seen<600;
 const openProject=()=>{setSection('project');setSidebar(false);setSearch('');setError('');};
 const choose=(id:string)=>{setProjectId(state.threads.find(t=>t.id===id)?.project_id||'');setSelected(id);setSection('threads');setSidebar(false);setError('');};
 return <div className="workspace flex w-screen overflow-hidden bg-background text-foreground">
  {sidebar&&<button className="sidebar-shade" aria-label="Закрыть меню" onClick={()=>setSidebar(false)}/>}
  <aside className={'workspace-sidebar '+(sidebar?'is-open':'')}><div className="sidebar-heading"><MessageSquare size={19}/><strong>Codex Workspace</strong><button className="icon-button mobile-only" onClick={()=>setSidebar(false)} aria-label="Закрыть меню"><X size={18}/></button></div>
   <select className="thread-search" aria-label="Проект" value={activeProject?.id||''} onChange={e=>{const id=e.target.value;setProjectId(id);setSelected(state.threads.find(t=>t.project_id===id)?.id||'');setSection('project');setSearch('');setProjectExpanded(true);}}>{projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select>
   <button className="project-label" onClick={()=>setProjectExpanded(value=>!value)} aria-expanded={projectExpanded} aria-controls="sidebar-project-tasks"><Folder size={15}/><strong>{activeProject?.title||'Проекты'}</strong>{projectExpanded?<ChevronDown size={14}/>:<ChevronRight size={14}/>}</button>
   <div id="sidebar-project-tasks" className="sidebar-project-tasks" hidden={!projectExpanded}><input className="thread-search" placeholder="Найти тред…" aria-label="Найти тред" value={search} onChange={e=>setSearch(e.target.value)}/>
   <nav className="thread-list">{projectThreads.filter(t=>t.title.toLowerCase().includes(search.toLowerCase())).map(t=><button key={t.id} className={'thread-row '+(selected===t.id&&section==='threads'?'selected':'')} onClick={()=>choose(t.id)}><MessageSquare size={15}/><span>{t.title}</span>{t.status==='active'&&<span className="activity-dot" title="Активная задача"/>}</button>)}{projectThreads.length===0&&<p className="small muted empty-threads">{owner?'Список тредов появится после синхронизации с Codex.':'Владелец ещё не выдал доступ к тредам.'}</p>}</nav></div>
   {owner&&<div className="owner-navigation"><button className={'thread-row '+(section==='approvals'?'selected':'')} onClick={()=>{setSection('approvals');setSidebar(false);}}><Inbox size={16}/><span>На одобрение</span>{waiting.length>0&&<span className="count">{waiting.length}</span>}</button><button className={'thread-row '+(section==='access'?'selected':'')} onClick={()=>{setSection('access');setSidebar(false);}}><ShieldCheck size={16}/><span>Доступ к тредам</span></button></div>}
   {<div className="weekly-quota small" aria-label="Недельная квота Codex">{state.weekly_quota?<><strong>Неделя: {Date.now()/1000>=state.weekly_quota.resets_at?'ожидаем обновления':`${Math.round(100-state.weekly_quota.used_percent)}% осталось`}</strong><progress max={100} value={Math.max(0,100-state.weekly_quota.used_percent)} aria-label="Остаток недельной квоты"/><span className="muted">Сброс: {new Date(state.weekly_quota.resets_at*1000).toLocaleString('ru-RU')}</span><span className="muted">Данные на {new Date(state.weekly_quota.observed_at*1000).toLocaleString('ru-RU')}</span></>:<span className="muted">Недельная квота пока неизвестна</span>}</div>}
   <PushSettings/>
   {owner&&<Diagnostics/>}
   <div className="sidebar-bottom"><span className="small muted">{owner?'Владелец':'Участник'}</span><button className="icon-button" onClick={()=>setDark(!dark)} aria-label={dark?'Светлая тема':'Тёмная тема'}>{dark?<Sun size={17}/>:<Moon size={17}/>}</button><button className="icon-button" onClick={logout} disabled={busy} aria-label="Выйти"><LogOut size={17}/></button></div>
  </aside>
  <div className="main-column"><header className="workspace-header"><button className="icon-button mobile-only" onClick={()=>setSidebar(true)} aria-label="Открыть треды"><Menu size={20}/></button><div className="header-title"><button className="project-link muted" onClick={openProject} aria-label={'Открыть проект '+(activeProject?.title||'')}>{activeProject?.title||'Проекты'}</button><ChevronRight size={14}/><strong>{section==='project'?'Задачи':section==='approvals'?'Одобрения':section==='access'?'Доступ':thread?.title||'Треды'}</strong></div><span className={'connection '+(online?'online':'')}><Circle size={8} fill="currentColor"/>{online?'Codex на связи':'Ожидаем Codex'}</span><button className="icon-button" onClick={()=>void refresh()} aria-label="Обновить"><RefreshCw size={16}/></button></header>
   {error&&<div className="error-banner" role="alert">{error}<button onClick={()=>setError('')} aria-label="Закрыть ошибку"><X size={16}/></button></div>}
   <main key={section} className="workspace-main" ref={scroll.ref} onScroll={scroll.onScroll} style={{overflowAnchor:'none'}}>
    {section==='project'?<ProjectPanel activeProject={activeProject} projectThreads={projectThreads} search={search} setSearch={setSearch} choose={choose} owner={owner}/>:section==='access'?<AccessPanel state={state} projects={projects} busy={busy} action={action}/>:
     <Conversation state={state} section={section} selected={selected} thread={thread} history={history} busy={busy} online={online} action={action} setDiff={setDiff}/>}
   </main>
   {section==='threads'&&sending===selected&&<div className="request-activity sending-activity" role="status">Отправляю…</div>}
   {section==='threads'&&thread?.read_only&&<p className="composer-note">Эта задача доступна только для чтения.</p>}
   {section==='threads'&&thread&&!thread.read_only&&<Composer composer={composer} selected={selected} thread={thread} busy={busy} direct={direct}/>}
  </div>{diff&&<DiffViewerDialog item={diff} onClose={()=>setDiff(null)}/>}<Toaster/>
 </div>;
}
