import { useLayoutEffect, useRef } from 'react';

type Position={bottom:boolean;top:number;anchor?:string;offset?:number};

// Store only positions, never conversation text or authentication data.
export function useConversationScroll(key:string,ready:boolean,before:string|null,loadOlder:(before:string)=>void){
 const ref=useRef<HTMLElement>(null);
 const active=useRef('');
 const target=useRef<Position>({bottom:true,top:0});
 const restored=useRef(false);
 const requested=useRef<string|null>(null);
 const persist=()=>{try{sessionStorage.setItem('workspace-scroll:'+active.current,JSON.stringify(target.current));}catch{/* Storage may be disabled. */}};
 const remember=()=>{
  const el=ref.current;if(!el||!key||!restored.current||active.current!==key)return;
  const top=el.getBoundingClientRect().top;
  const anchor=Array.from(el.querySelectorAll<HTMLElement>('[data-scroll-id]')).find(node=>node.getBoundingClientRect().bottom>top);
  target.current={bottom:el.scrollHeight-el.clientHeight-el.scrollTop<32,top:el.scrollTop,...(anchor?{anchor:anchor.dataset.scrollId,offset:anchor.getBoundingClientRect().top-top}:{})};
  persist();
 };
 useLayoutEffect(()=>{
  const el=ref.current;if(!el||!key)return;
  if(active.current!==key){
   active.current=key;restored.current=false;requested.current=null;target.current={bottom:true,top:0};
   try{
    const saved=JSON.parse(sessionStorage.getItem('workspace-scroll:'+key)||'null');
    if(saved&&typeof saved.bottom==='boolean'&&Number.isFinite(saved.top))target.current=saved;
   }catch{/* Start at the end when saved state is unavailable. */}
  }
  if(!ready)return;
  const restore=()=>{
   const pos=target.current;
   const anchor=pos.anchor?Array.from(el.querySelectorAll<HTMLElement>('[data-scroll-id]')).find(node=>node.dataset.scrollId===pos.anchor):null;
   if(!pos.bottom&&pos.anchor&&!anchor&&before){
    if(requested.current!==before){requested.current=before;loadOlder(before);}
    return;
   }
   if(pos.bottom)el.scrollTop=el.scrollHeight;
   else if(anchor)el.scrollTop+=anchor.getBoundingClientRect().top-el.getBoundingClientRect().top-(pos.offset||0);
   else el.scrollTop=pos.top;
   restored.current=true;
  };
  restore();
  const content=el.firstElementChild;
  const observer=new ResizeObserver(restore);
  if(content)observer.observe(content);
  return()=>observer.disconnect();
 });
 return {ref,onScroll:remember};
}
