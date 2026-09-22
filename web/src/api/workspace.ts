import {encryptedActive,encryptedState,encryptedSend} from '../crypto/client';
import { request } from './transport';
import type { WorkspaceState, Message } from './types';
export const fetchState=()=>encryptedActive()?encryptedState():request<WorkspaceState>('/web/state',{});
export const sendMessage=(thread:string,text:string,request_id:string,attachments:string[]=[])=>encryptedActive()?encryptedSend(thread,text,request_id,attachments):request<Message>('/web/messages',{thread,text,request_id,attachments});
