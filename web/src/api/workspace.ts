import { request } from './transport';
import type { WorkspaceState, Message } from './types';
export const fetchState=()=>request<WorkspaceState>('/web/state',{});
export const sendMessage=(thread:string,text:string,request_id:string,attachments:string[]=[])=>request<Message>('/web/messages',{thread,text,request_id,attachments});
export const decide=(message:Message,decision:'approved'|'rejected')=>request<Message>('/web/decisions',{id:message.id,snapshot:message.snapshot,decision});
export const grant=(user_id:number,threads:string[],projects?:string[],denied_threads?:string[])=>request('/web/grants',{user_id,threads,projects,denied_threads});

export const setMemberPolicy=(user_id:number,requires_approval:boolean)=>request('/web/member-policy',{user_id,requires_approval});
