const prefix=()=>'/web/e2ee/push/';
import { request } from './transport';
export const pushConfig=()=>request<{public_key:string}>(prefix()+'config',{});
export const pushSubscribe=(subscription:PushSubscriptionJSON)=>request(prefix()+'subscribe',{subscription});
export const pushUnsubscribe=(subscription:PushSubscriptionJSON)=>request(prefix()+'unsubscribe',{subscription});
