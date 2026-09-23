import {LockedDevice} from './crypto/LockedDevice';
import {DeviceSettings} from './crypto/DeviceSettings';
/* Workspace shell adapted from LuSeptem/codex-webui AppShell; MIT notice in licenses/. */
import { useEffect, useState } from 'react';
import {PairingScreen} from './crypto/PairingScreen';
import { ChevronDown, ChevronRight, Circle, Folder, LogOut, Menu, MessageSquare, Moon, RefreshCw, Sun, X } from 'lucide-react';
import { DiffViewerDialog } from './components/diff/DiffViewerDialog';
import { useThreadHistory } from './History';
import { useConversationScroll } from './ConversationScroll';
import {PushSettings} from './PushSettings';
import { Toaster } from './components/ui/Toaster';
import type { FileChangeItem } from './types/api';
import { useWorkspaceNavigation } from './workspace/useWorkspaceNavigation';
import { useWorkspaceSession } from './workspace/useWorkspaceSession';

import { ProjectPanel } from './workspace/ProjectPanel';
import { Diagnostics } from './workspace/Diagnostics';
import { Composer } from './workspace/Composer';
import { useComposer } from './workspace/useComposer';
import { LoginPage } from './workspace/LoginPage';
import { Conversation } from './workspace/Conversation';

export function App({initialPairingFragment=''}:{initialPairingFragment?:string}){
 const [pairingFragment,setPairingFragment]=useState(initialPairingFragment);
 const {state,checking,busy,setBusy,error,setError,resetVersion,config,preparing,prepare,refresh,action,enter,logout,cancelLogin}=useWorkspaceSession();
 const {projectExpanded,setProjectExpanded,selected,section,sidebar,setSidebar,search,setSearch,projects,thread,activeProject,projectThreads,openProject,choose,chooseProject}=useWorkspaceNavigation(state,resetVersion,setError);
 const [diff,setDiff]=useState<FileChangeItem|null>(null);
 const [dark,setDark]=useState(()=>localStorage.getItem('workspace-theme')!=='light');
 useEffect(()=>{document.documentElement.classList.toggle('dark',dark);localStorage.setItem('workspace-theme',dark?'dark':'light');},[dark]);
 const composer=useComposer({selected,sessionVersion:resetVersion,busy,setBusy,setError,action});
 const {sending}=composer;
 useEffect(()=>{setDiff(null);},[resetVersion]);
 const history=useThreadHistory(selected,Boolean(state)&&section==='threads');
 const scroll=useConversationScroll(state&&section==='threads'?`${state.user.id}:${selected}`:'',Boolean(history.page),history.page?.before||null,before=>void history.refresh(before));
 if(!state)return <LoginPage checking={checking} ready={Boolean(config)} busy={busy} preparing={preparing} error={error} enter={enter} cancel={cancelLogin} prepare={prepare}/>;
 if(pairingFragment)return <PairingScreen key={String(state.user.id)} account={String(state.user.id)} fragment={pairingFragment} close={()=>{setPairingFragment('');void refresh();}}/>;
 if(state.encryption_locked)return <LockedDevice workspace={state.encryption!.workspace} pair={setPairingFragment} logout={logout}/>;
 const online=state.collector_seen!==null&&Date.now()/1000-state.collector_seen<600;
 return <div className="workspace flex w-screen overflow-hidden bg-background text-foreground">
  {sidebar&&<button className="sidebar-shade" aria-label="Закрыть меню" onClick={()=>setSidebar(false)}/>}
  <aside id="workspace-navigation" aria-label="Проекты и задачи" className={'workspace-sidebar '+(sidebar?'is-open':'')}><div className="sidebar-heading"><MessageSquare size={19}/><strong>Codex Workspace</strong><button className="icon-button mobile-only" onClick={()=>setSidebar(false)} aria-label="Закрыть меню"><X size={18}/></button></div>
   <div className="project-switcher"><Folder size={17}/><select aria-label="Проект" value={activeProject?.id||''} onChange={e=>chooseProject(e.target.value)}>{projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select><button className="icon-button" onClick={()=>setProjectExpanded(value=>!value)} aria-label={projectExpanded?'Свернуть задачи проекта':'Развернуть задачи проекта'} aria-expanded={projectExpanded} aria-controls="sidebar-project-tasks">{projectExpanded?<ChevronDown size={17}/>:<ChevronRight size={17}/>}</button></div>
   <div id="sidebar-project-tasks" className="sidebar-project-tasks" hidden={!projectExpanded}><input className="thread-search" placeholder="Найти тред…" aria-label="Найти тред" value={search} onChange={e=>setSearch(e.target.value)}/>
   <nav className="thread-list">{projectThreads.filter(t=>t.title.toLowerCase().includes(search.toLowerCase())).map(t=><button key={t.id} className={'thread-row '+(selected===t.id&&section==='threads'?'selected':'')} onClick={()=>choose(t.id)}><MessageSquare size={15}/><span>{t.title}</span>{t.status==='active'&&<span className="activity-dot" title="Активная задача"/>}</button>)}{projectThreads.length===0&&<p className="small muted empty-threads">Список тредов появится после синхронизации с Codex.</p>}</nav></div>
   {<div className="weekly-quota small" aria-label="Недельная квота Codex">{state.weekly_quota?<><strong>Неделя: {Date.now()/1000>=state.weekly_quota.resets_at?'ожидаем обновления':`${Math.round(100-state.weekly_quota.used_percent)}% осталось`}</strong><progress max={100} value={Math.max(0,100-state.weekly_quota.used_percent)} aria-label="Остаток недельной квоты"/><span className="muted">Сброс: {new Date(state.weekly_quota.resets_at*1000).toLocaleString('ru-RU')}</span><span className="muted">Данные на {new Date(state.weekly_quota.observed_at*1000).toLocaleString('ru-RU')}</span></>:<span className="muted">Недельная квота пока неизвестна</span>}</div>}
   {state.encryption&&<DeviceSettings/>}
   <PushSettings/>
   <Diagnostics/>
   <div className="sidebar-bottom"><span className="small muted">Личное пространство</span><button className="icon-button" onClick={()=>setDark(!dark)} aria-label={dark?'Светлая тема':'Тёмная тема'}>{dark?<Sun size={17}/>:<Moon size={17}/>}</button><button className="icon-button" onClick={logout} disabled={busy} aria-label="Выйти"><LogOut size={17}/></button></div>
  </aside>
  <div className="main-column"><header className="workspace-header"><button className="icon-button mobile-only task-menu-button" onClick={()=>setSidebar(true)} aria-label="Открыть треды" aria-expanded={sidebar} aria-controls="workspace-navigation"><Menu size={20}/><span>Задачи</span></button><div className="header-title"><button className="project-link muted" onClick={openProject} aria-label={'Открыть проект '+(activeProject?.title||'')}>{activeProject?.title||'Проекты'}</button><ChevronRight size={14}/><strong>{section==='project'?'Задачи':thread?.title||'Треды'}</strong></div><span className={'connection '+(online?'online':'')}><Circle size={8} fill="currentColor"/>{online?'Codex на связи':'Ожидаем Codex'}</span><button className="icon-button" onClick={()=>void refresh()} aria-label="Обновить"><RefreshCw size={16}/></button></header>
   {error&&<div className="error-banner" role="alert">{error}<button onClick={()=>setError('')} aria-label="Закрыть ошибку"><X size={16}/></button></div>}
   <main key={section} className="workspace-main" ref={scroll.ref} onScroll={scroll.onScroll} style={{overflowAnchor:'none'}}>
    {section==='project'?<ProjectPanel activeProject={activeProject} projectThreads={projectThreads} search={search} setSearch={setSearch} choose={choose}/>:
     <Conversation state={state} section={section} selected={selected} thread={thread} history={history} busy={busy} online={online} action={action} setDiff={setDiff}/>}
   </main>
   {section==='threads'&&sending===selected&&<div className="request-activity sending-activity" role="status">Отправляю…</div>}
   {section==='threads'&&thread?.read_only&&<p className="composer-note">Эта задача доступна только для чтения.</p>}
   {section==='threads'&&thread&&!thread.read_only&&<Composer composer={composer} selected={selected} thread={thread} busy={busy}/>}
  </div>{diff&&<DiffViewerDialog item={diff} onClose={()=>setDiff(null)}/>}<Toaster/>
 </div>;
}
