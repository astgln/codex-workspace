import { request } from './transport';
import type { HistoryPage } from './types';
export const fetchHistory=(thread:string,before?:string)=>request<HistoryPage>('/web/history',{thread,...(before?{before}:{})});
