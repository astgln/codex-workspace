import {encryptedActive,encryptedState,encryptedSend,encryptedControl} from '../../features/encryption/client';
import { request } from './transport';
import type { WorkspaceState, Message } from './types';
export const fetchState=()=>encryptedActive()?encryptedState():request<WorkspaceState>('/web/state',{});
export const sendMessage=(thread:string,text:string,request_id:string,attachments:string[]=[])=>encryptedActive()?encryptedSend(thread,text,request_id,attachments):request<Message>('/web/messages',{thread,text,request_id,attachments});

export const decide=(message:Message,decision:'approved'|'rejected')=>encryptedActive()?encryptedControl('decide',{id:message.id,snapshot:message.snapshot,decision}):request<Message>('/web/decisions',{id:message.id,snapshot:message.snapshot,decision});
export const grant=(user_id:number,threads:string[],projects?:string[],denied_threads?:string[])=>encryptedActive()?encryptedControl('grants',{user_id,threads,...(projects?{projects}:{}),...(denied_threads?{denied_threads}:{})}):request('/web/grants',{user_id,threads,projects,denied_threads});

export const setMemberPolicy=(user_id:number,requires_approval:boolean)=>encryptedActive()?encryptedControl('member-policy',{user_id,requires_approval}):request('/web/member-policy',{user_id,requires_approval});
