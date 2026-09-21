import { useEffect, useRef, useState } from 'react';
import type { WorkspaceState } from '../api';

export type Section = 'threads' | 'project';

export function useWorkspaceNavigation(state: WorkspaceState | null, resetVersion: number, setError: (value: string) => void) {
  const [projectId, setProjectId] = useState('');
  const [projectExpanded, setProjectExpanded] = useState(true);
  const [selected, setSelected] = useState('');
  const [section, setSection] = useState<Section>('threads');
  const [sidebar, setSidebar] = useState(false);
  const [search, setSearch] = useState('');
  const initialized = useRef(false);
  const latest = useRef(state);
  latest.current = state;

  const remember = (project: string, task: string, view: 'threads' | 'project') => {
    if (!latest.current) return;
    try { localStorage.setItem(`workspace-navigation:${latest.current.user.id}`, JSON.stringify({project, task, view})); } catch { /* Storage may be unavailable. */ }
  };
  const orderedThreads = [...(state?.threads || [])].sort((a,b) => (b.updated_at || 0) - (a.updated_at || 0));
  const choose = (id: string) => {
    const task = latest.current?.threads.find(task => task.id === id);
    if (!task) return;
    setProjectId(task.project_id || ''); setSelected(id); setSection('threads');
    setSidebar(false); setError('');
    remember(task.project_id || '', id, 'threads');
  };
  useEffect(() => {
    initialized.current = false;
    setSelected(''); setSection('threads'); setProjectId(''); setSearch(''); setSidebar(false);
  }, [resetVersion]);
  useEffect(() => {
    if (!state) return;
    if (!initialized.current) {
      initialized.current = true;
      let saved: {project?:string;task?:string;view?:string} = {};
      try { saved = JSON.parse(localStorage.getItem(`workspace-navigation:${state.user.id}`) || '{}') || {}; } catch { /* Ignore obsolete storage. */ }
      const restored = state.threads.find(task => task.id === saved.task);
      if (saved.view === 'project' && state.projects?.some(project => project.id === saved.project)) {
        setProjectId(saved.project!); setSelected(restored && restored.project_id === saved.project ? restored.id : ''); setSection('project');
        return;
      }
      const next = restored || orderedThreads[0];
      setSelected(next?.id || ''); setProjectId(next?.project_id || '');
    } else if (section === 'threads' && !state.threads.some(task => task.id === selected)) {
      const next = orderedThreads[0];
      setSelected(next?.id || ''); setProjectId(next?.project_id || '');
    }
  }, [state, selected, section]);
  useEffect(() => {
    const follow = () => {
      const current = latest.current;
      if (!current) return;
      const hash = location.hash;
      if (hash.startsWith('#thread=')) choose(hash.slice(8));
    };
    // Rebind only at authentication boundaries. Every event reads the latest
    // current catalog, but polling must not reapply an old notification link.
    follow();
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  }, [Boolean(state)]);

  const activity = new Map<string, number>();
  for (const task of orderedThreads) if (task.project_id) activity.set(task.project_id, Math.max(activity.get(task.project_id) || 0, task.updated_at || 0));
  const projects = [...(state?.projects || [{id:'legacy',title:'Проект'}])].sort((a,b) => (activity.get(b.id) || 0) - (activity.get(a.id) || 0));
  const thread = state?.threads.find(task => task.id === selected);
  const activeProject = projects.find(project => project.id === projectId) ||
    projects.find(project => project.id === thread?.project_id) || projects[0];
  const projectThreads = orderedThreads.filter(task => !task.project_id || task.project_id === activeProject?.id);
  const openProject = () => { setSection('project'); setSidebar(false); setSearch(''); setError(''); remember(activeProject?.id || '', selected, 'project'); };
  const chooseProject = (id: string) => {
    if (!projects.some(project => project.id === id)) return;
    const task = orderedThreads.find(task => task.project_id === id);
    setProjectId(id); setSelected(task?.id || '');
    remember(id, task?.id || '', 'project');
    setSection('project'); setSearch(''); setProjectExpanded(true);
  };
  return {projectExpanded,setProjectExpanded,selected,section,setSection,sidebar,setSidebar,
    search,setSearch,projects,thread,activeProject,projectThreads,openProject,choose,chooseProject};
}
