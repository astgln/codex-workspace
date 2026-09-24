import { AgentMessageCard } from '../../shared/components/events/AgentMessageCard';
import { FileChangeCard } from '../../shared/components/events/FileChangeCard';
import { PlanUpdateCard } from '../../shared/components/events/PlanUpdateCard';
import { ErrorCard } from '../../shared/components/events/ErrorCard';
import type { FileChangeItem, ResponseItem } from '../../shared/types/api';

export function PublicEvent({event,openDiff}:{event:ResponseItem;openDiff:(item:FileChangeItem)=>void}){switch(event.type){case 'agent_message':return <AgentMessageCard item={event}/>;case 'file_change':return <FileChangeCard item={event} onOpenDiff={openDiff}/>;case 'plan_update':return <PlanUpdateCard item={event}/>;case 'error':return <ErrorCard item={event}/>;default:return null;}}
