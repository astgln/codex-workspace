/** Shared presentation contract for transport and execution states. */
export const requestStatuses={
 queued:{label:'Ожидает Codex',activity:'В очереди Codex…'},
 delivered:{label:'Передано в Codex',activity:'Ожидаю ответа Codex…'},
 waiting_for_task:{label:'Ожидаем освобождения задачи в Codex',activity:'Ожидаем освобождения задачи в Codex…'},
 waiting_for_settings:{label:'Ожидаем доступ к настройкам задачи',activity:'Ожидаем доступ к настройкам задачи…'},
 running:{label:'Codex работает',activity:'Думаю…'},
 completed:{label:'Ответ готов',activity:null},
 failed:{label:'Ошибка обработки',activity:null},
 needs_input:{label:'Нужен ответ',activity:null},
 rejected:{label:'Отклонено',activity:null},
 expired:{label:'Истёк срок запроса',activity:null},
 target_unavailable:{label:'Тред недоступен',activity:null},
 superseded:{label:'Заменено новой версией',activity:null},
} as const;
export type RequestStatus=keyof typeof requestStatuses;
export function requestStatus(value:string){
 return Object.hasOwn(requestStatuses,value)?requestStatuses[value as RequestStatus]:{label:'Статус обновляется',activity:null};
}
