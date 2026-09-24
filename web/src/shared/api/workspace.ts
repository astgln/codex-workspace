import {encryptedState,encryptedSend,encryptedControl} from '../../features/encryption/client';
import type {Message} from './types';
export const fetchState=encryptedState;
export const sendMessage=encryptedSend;
export const decide=(message:Message,decision:'approved'|'rejected')=>encryptedControl('decide',{id:message.id,snapshot:message.snapshot,decision});
export const grant=(user_id:number,threads:string[],projects?:string[],denied_threads?:string[])=>encryptedControl('grants',{user_id,threads,...(projects?{projects}:{}),...(denied_threads?{denied_threads}:{})});
export const setMemberPolicy=(user_id:number,requires_approval:boolean)=>encryptedControl('member-policy',{user_id,requires_approval});
