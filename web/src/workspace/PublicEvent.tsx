import { AgentMessageCard } from '../components/events/AgentMessageCard';
import { FileChangeCard } from '../components/events/FileChangeCard';
import { PlanUpdateCard } from '../components/events/PlanUpdateCard';
import { ErrorCard } from '../components/events/ErrorCard';
import type { FileChangeItem, ResponseItem } from '../types/api';

export function PublicEvent({event,openDiff}:{event:ResponseItem;openDiff:(item:FileChangeItem)=>void}){switch(event.type){case 'agent_message':return <AgentMessageCard item={event}/>;case 'file_change':return <FileChangeCard item={event} onOpenDiff={openDiff}/>;case 'plan_update':return <PlanUpdateCard item={event}/>;case 'error':return <ErrorCard item={event}/>;default:return null;}}
