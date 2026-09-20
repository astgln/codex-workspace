import type { ResponseItem } from '../types/api';
export type Thread = { project_id?:string; id:string; title:string; status:string; read_only?:boolean };
export type Attachment = {id:string;name:string;size:number;sha256:string};
export type Message = { id:number; sender:number; thread:string; text:string; created:number; expires:number; status:string; snapshot:string; events?:ResponseItem[]; result_status?:string; attachments?:Attachment[] };
export type WorkspaceState = {projects?:{id:string;title:string}[];weekly_quota?:{used_percent:number;resets_at:number;observed_at:number}|null;user:{id:number;role:'owner'|'member';requires_approval?:boolean};threads:Thread[];messages:Message[];members?:{id:number;username:string;projects?:string[];denied_threads?:string[];requires_approval?:boolean;threads:string[]}[];catalog_updated:number|null;collector_seen:number|null};
export type HistoryMessage={id:string;position:string;role:'user'|'assistant';text:string;created:number};
export type HistoryPage={messages:HistoryMessage[];before:string|null;synced_at:number|null;loading_older:boolean;pending:boolean};
