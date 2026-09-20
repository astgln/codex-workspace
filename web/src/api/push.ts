import { request } from './transport';
export const pushConfig=()=>request<{public_key:string}>('/web/push/config',{});
export const pushSubscribe=(subscription:PushSubscriptionJSON)=>request('/web/push/subscribe',{subscription});
export const pushUnsubscribe=(subscription:PushSubscriptionJSON)=>request('/web/push/unsubscribe',{subscription});
