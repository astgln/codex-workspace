import {encryptedActive,encryptedHistory} from '../crypto/client';
import { request } from './transport';
import type { HistoryPage } from './types';
export const fetchHistory=(thread:string,before?:string)=>encryptedActive()?encryptedHistory(thread):request<HistoryPage>('/web/history',{thread,...(before?{before}:{})});
