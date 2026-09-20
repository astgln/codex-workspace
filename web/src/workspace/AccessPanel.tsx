import { grant, setMemberPolicy } from '../api';
import type { WorkspaceState } from '../api';

type Props = {
 state: WorkspaceState;
 projects: {id:string;title:string}[];
 busy: boolean;
 action: (operation:()=>Promise<unknown>)=>Promise<void>;
};

export function AccessPanel({state,projects,busy,action}:Props){
 return <div className="content-width access-panel"><h1>Доступ к тредам</h1><p className="muted">Доступ ко всему проекту включает новые задачи. Снимите галочку у отдельной задачи, чтобы закрыть её. Настройка одобрения применяется к новым запросам.</p>{!state.members?.length&&<p className="empty-note">Участники появятся здесь после первого входа.</p>}{state.members?.map(member=><section key={member.id} className="member-card"><h2>@{member.username}</h2><label className="grant-row"><input type="checkbox" checked={member.requires_approval!==false} disabled={busy} onChange={e=>void action(()=>setMemberPolicy(member.id,e.target.checked))}/><span>Требовать одобрение запросов</span></label><p className="small muted">{member.requires_approval===false?'Новые запросы сразу попадают в очередь Codex.':'Новые запросы ждут вашего одобрения.'}</p>{projects.map(project=><div key={project.id} className="access-project"><label className="grant-row"><input type="checkbox" aria-label={'Весь проект '+project.title+' для @'+member.username} checked={(member.projects||[]).includes(project.id)} disabled={busy} onChange={e=>void action(()=>grant(member.id,member.threads,e.target.checked?[...(member.projects||[]),project.id]:(member.projects||[]).filter(id=>id!==project.id),member.denied_threads||[]))}/><strong>{project.title} — весь проект</strong></label>{state.threads.filter(t=>!t.project_id||t.project_id===project.id).map(t=>{const inherited=(member.projects||[]).includes(project.id);const denied=(member.denied_threads||[]).includes(t.id);const allowed=!denied&&(inherited||member.threads.includes(t.id));return <label key={t.id} className="grant-row task-grant"><input type="checkbox" aria-label={t.title+' для @'+member.username} checked={allowed} disabled={busy} onChange={e=>{const checked=e.target.checked;const explicit=member.threads.filter(id=>id!==t.id);if(checked&&!inherited)explicit.push(t.id);const exclusions=(member.denied_threads||[]).filter(id=>id!==t.id);if(!checked&&inherited)exclusions.push(t.id);void action(()=>grant(member.id,explicit,member.projects||[],exclusions));}}/><span>{t.title}{denied?' · закрыта':inherited?' · доступ через проект':''}</span></label>})}</div>)}</section>)}</div>;
}
