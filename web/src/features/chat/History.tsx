import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchHistory, type HistoryMessage, type HistoryPage } from '../../shared/api/index';

export function useThreadHistory(thread:string,enabled:boolean){
 const [page,setPage]=useState<(HistoryPage&{thread:string})|null>(null);
 const [error,setError]=useState(''),[busy,setBusy]=useState(false);
 const current=useRef(thread);current.current=thread;
 const refresh=useCallback(async(before?:string)=>{
  if(!thread||!enabled)return;
  setBusy(true);
  try{
   const next=await fetchHistory(thread,before);
   if(current.current!==thread)return;
   setPage(old=>{
    const existing=old?.thread===thread?old:null;
    const messages=new Map<string,HistoryMessage>((existing?.messages||[]).map(m=>[m.id,m]));
    next.messages.forEach(m=>messages.set(m.id,m));
    const ordered=[...messages.values()].sort((a,b)=>a.position.localeCompare(b.position));
    return {...next,thread,messages:ordered,before:before?next.before:existing&&existing.messages.length>50?existing.before:next.before};
   });setError('');
  }catch(e){if(current.current===thread)setError(e instanceof Error?e.message:'История пока недоступна.');}
  finally{if(current.current===thread)setBusy(false);}
 },[thread,enabled]);
 useEffect(()=>{
  setPage(null);setError('');void refresh();
  if(!enabled||!thread)return;
  const timer=setInterval(()=>{if(document.visibilityState==='visible')void refresh();},10000);
  return()=>clearInterval(timer);
 },[refresh,thread,enabled]);
 return {page:page?.thread===thread?page:null,error,busy,refresh};
}
