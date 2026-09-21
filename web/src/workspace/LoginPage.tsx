import { MessageSquare } from 'lucide-react';

type Props = {
 checking: boolean;
 ready: boolean;
 busy: boolean;
 preparing: boolean;
 error: string;
 enter: () => void;
 cancel: () => void;
 prepare: () => void;
};

export function LoginPage({checking, ready, busy, preparing, error, enter, cancel, prepare}: Props) {
 return (
<div className="login-page"><div className="login-card"><div className="brand-mark"><MessageSquare size={26}/></div><p className="eyebrow">WARCRAFT WORKSPACE</p><h1>Ваши задачи Codex.<br/>В одном окне.</h1><p className="muted">Треды, сообщения и результаты работы — с компьютера или телефона.</p><button className="primary login-button" disabled={checking||!ready||busy} onClick={enter}>{checking?'Проверяем сессию…':busy?'Ожидаем Telegram…':preparing?'Загружаем вход…':'Войти через Telegram'}</button>{busy&&<div role="status" className="small muted"><p>Завершите вход в окне Telegram. Если оно не открылось, откройте этот сайт в обычном браузере.</p><button className="quiet" onClick={cancel}>Отменить вход</button></div>}{error&&<div className="error-box" role="alert">{error}<button onClick={prepare}>Повторить</button></div>}<p className="small muted">Доступ только для приглашённых участников.<br/>Владелец задаёт доступ к задачам и порядок одобрения запросов участников.</p></div><footer>На основе Codex Web UI · Независимый проект</footer></div>
 );
}
