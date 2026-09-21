import { request } from './transport';
import type { WorkspaceState, Message } from './types';
export const fetchState=()=>request<WorkspaceState>('/web/state',{});
export const sendMessage=(thread:string,text:string,request_id:string,attachments:string[]=[])=>request<Message>('/web/messages',{thread,text,request_id,attachments});
