import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

test('push worker displays the task and message with bounded text and a safe link',async()=>{
 const handlers:Record<string,Function>={};
 const shown:any[]=[];
 const self={addEventListener:(type:string,fn:Function)=>handlers[type]=fn,
   registration:{showNotification:async(title:string,options:any)=>{shown.push({title,...options});}}};
 runInNewContext(readFileSync(new URL('../public/sw.js',import.meta.url),'utf8'),{self,URL});
 let completion:Promise<unknown>=Promise.resolve();
 handlers.push({data:{json:()=>({title:'Launcher',body:'Подключение исправлено',url:'/#thread=task-1'})},waitUntil:(p:Promise<unknown>)=>completion=p});
 await completion;
 expect(shown[0]).toMatchObject({title:'Launcher',body:'Подключение исправлено',data:{url:'/#thread=task-1'}});
 handlers.push({data:{json:()=>({title:'😀'.repeat(1000),body:'😀'.repeat(1000),url:'https://untrusted.example/'})},waitUntil:(p:Promise<unknown>)=>completion=p});
 await completion;
 expect(Array.from(shown[1].title)).toHaveLength(120);
 expect(Array.from(shown[1].body)).toHaveLength(520);
 expect(shown[1].data.url).toBe('/');
});
