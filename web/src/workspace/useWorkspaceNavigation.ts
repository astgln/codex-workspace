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
  const latest = useRef(state);
  latest.current = state;

  const choose = (id: string) => {
    const task = latest.current?.threads.find(task => task.id === id);
    if (!task) return;
    setProjectId(task.project_id || ''); setSelected(id); setSection('threads');
    setSidebar(false); setError('');
  };
  useEffect(() => {
    setSelected(''); setSection('threads'); setProjectId(''); setSearch(''); setSidebar(false);
  }, [resetVersion]);
  useEffect(() => {
    if (!state) return;
    if (section === 'threads' && !state.threads.some(task => task.id === selected)) {
      const next = state.threads[0];
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

  const projects = state?.projects || [{id:'legacy',title:'Проект'}];
  const thread = state?.threads.find(task => task.id === selected);
  const activeProject = projects.find(project => project.id === projectId) ||
    projects.find(project => project.id === thread?.project_id) || projects[0];
  const projectThreads = state?.threads.filter(task => !task.project_id || task.project_id === activeProject?.id) || [];
  const openProject = () => { setSection('project'); setSidebar(false); setSearch(''); setError(''); };
  const chooseProject = (id: string) => {
    if (!projects.some(project => project.id === id)) return;
    setProjectId(id); setSelected(state?.threads.find(task => task.project_id === id)?.id || '');
    setSection('project'); setSearch(''); setProjectExpanded(true);
  };
  return {projectExpanded,setProjectExpanded,selected,section,setSection,sidebar,setSidebar,
    search,setSearch,projects,thread,activeProject,projectThreads,openProject,choose,chooseProject};
}
