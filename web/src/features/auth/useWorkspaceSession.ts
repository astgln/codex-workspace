import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, fetchState, login, prepareLogin, restoreSession, signOut } from '../../shared/api/index';
import type { WorkspaceState } from '../../shared/api/index';
import {clearEncryptedSession} from '../encryption/client';
import { disablePush } from '../notifications/PushSettings';

// Each session boundary invalidates outstanding workspace responses.
export function useWorkspaceSession() {
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [resetVersion, setResetVersion] = useState(0);
  const [config, setConfig] = useState<Awaited<ReturnType<typeof prepareLogin>> | null>(null);
  const [preparing, setPreparing] = useState(false);
  const generation = useRef(0);
  const preparation = useRef(0);
  const loginAttempt = useRef<AbortController | null>(null);

  const clearSession = useCallback(() => {
    clearEncryptedSession();
    generation.current++;
    setState(null);
    setBusy(false);
    setResetVersion(value => value + 1);
  }, []);
  const prepare = useCallback(() => {
    const current = ++preparation.current;
    setError(''); setConfig(null); setPreparing(true);
    prepareLogin().then(value => {
      if (current === preparation.current) setConfig(value);
    }).catch(error => {
      if (current === preparation.current) setError(error.message);
    }).finally(() => {
      if (current === preparation.current) setPreparing(false);
    });
  }, []);
  useEffect(() => {
    let active = true;
    restoreSession().then(next => { if (active) setState(next); })
      .catch(() => {}).finally(() => { if (active) setChecking(false); });
    return () => { active = false; generation.current++; preparation.current++; loginAttempt.current?.abort(); };
  }, []);
  const authenticated = Boolean(state);
  useEffect(() => { if (!authenticated && !checking) prepare(); }, [authenticated, checking, prepare]);

  const refresh = useCallback(async () => {
    const current = generation.current;
    try {
      const next = await fetchState();
      if (current !== generation.current) return;
      setState(next); setError('');
    } catch (error) {
      if (current !== generation.current) return;
      if (error instanceof ApiError && error.status === 401) clearSession();
      setError(error instanceof Error ? error.message : 'Не удалось обновить данные.');
    }
  }, [clearSession]);
  useEffect(() => {
    if (!authenticated) return;
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, 8000);
    return () => clearInterval(timer);
  }, [authenticated, refresh]);

  const action = async (operation: () => Promise<unknown>) => {
    const current = generation.current;
    setBusy(true); setError('');
    try {
      await operation();
      if (current === generation.current) await refresh();
    } catch (error) {
      if (current !== generation.current) return;
      if (error instanceof ApiError && error.status === 401) clearSession();
      setError(error instanceof Error ? error.message : 'Не удалось выполнить действие.');
    } finally { if (current === generation.current) setBusy(false); }
  };
  const enter = (deviceId?:string) => {
    if (!config) return;
    const attempt = new AbortController();
    loginAttempt.current = attempt;
    generation.current++;
    setBusy(true); setError('');
    const selection=deviceId?{devices:config.devices.filter(d=>d.deviceStamp===deviceId)}:config;
    login(selection, attempt.signal).then(next=>{if(!attempt.signal.aborted)setState(next);}).catch(error => {
      setError(error.message); setConfig(null);
    }).finally(() => { setBusy(false); loginAttempt.current = null; });
  };
  useEffect(() => {
    if (!config || busy || authenticated) return;
    const timer = setTimeout(prepare, 240000);
    return () => clearTimeout(timer);
  }, [config, busy, authenticated, prepare]);
  const logout = async () => {
    // Invalidate polls as soon as logout begins, before either network request.
    generation.current++;
    setBusy(true);
    try { await disablePush(); await signOut(); clearSession(); }
    catch (error) { setError(error instanceof Error ? error.message : 'Не удалось выйти.'); }
    finally { setBusy(false); }
  };
  return {state, checking, busy, setBusy, error, setError, resetVersion, config,
    preparing, prepare, refresh, action, enter, logout, cancelLogin: () => loginAttempt.current?.abort()};
}
