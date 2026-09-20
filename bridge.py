#!/usr/bin/env python3
"""Private text-only Telegram inbox for a Codex thread. Python stdlib only."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request

DEFAULT_STATE = Path(__file__).resolve().parent / '.local'
ACK = 'Сообщение получено в задаче Codex. Тест доставки и обратного ответа прошёл. Пока это проверка связи; разбор логов ещё не подключён.'


class BridgeError(Exception):
    pass


class Telegram:
    def __init__(self, token):
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
            raise BridgeError('Некорректный формат токена.')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, method, **params):
        request = urllib.request.Request(
            'https://api.telegram.org/bot' + self.token + '/' + method,
            data=json.dumps(params).encode(), headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=(30 if method == 'getUpdates' and params.get('timeout', 0) else 10)) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise BridgeError(f'Telegram HTTP {error.code}; URL и токен скрыты.') from None
        except urllib.error.URLError as error:
            raise BridgeError('Соединение с Telegram не удалось (' + type(error.reason).__name__ + '). Токен скрыт; настройки не сохранены, если это setup.') from None
        except (OSError, ValueError):
            raise BridgeError('Telegram недоступен или ответ некорректен; секреты скрыты.') from None
        if not result.get('ok'):
            raise BridgeError('Telegram отклонил запрос; подробности скрыты.')
        return result['result']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_token(path):
    try:
        if path.stat().st_mode & 0o077:
            raise BridgeError('Файл .env должен иметь права 0600.')
        values = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if key.strip() == 'TELEGRAM_BOT_TOKEN' and separator:
                values.append(value.strip().strip('"\''))
        if len(values) != 1 or not values[0]:
            raise BridgeError('Укажите один TELEGRAM_BOT_TOKEN в .env.')
        return values[0]
    except OSError:
        raise BridgeError('Не удалось прочитать .env с токеном.') from None


def load_config(state):
    try:
        return json.loads((state / 'config.json').read_text())
    except (OSError, ValueError):
        raise BridgeError('Сначала выполните setup.') from None


def save_config(state, value):
    path = state / 'config.json'
    temporary = state / 'config.tmp'
    with temporary.open('w') as stream:
        json.dump(value, stream)
    temporary.chmod(0o600)
    temporary.replace(path)


@contextlib.contextmanager
def exclusive(state):
    with (state / 'transport.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BridgeError('Другой процесс уже получает сообщения.') from None
        yield


class Queue:
    def __init__(self, state):
        self.db = sqlite3.connect(state / 'queue.sqlite3', timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER);
          INSERT OR IGNORE INTO cursor VALUES (1,0);
          CREATE TABLE IF NOT EXISTS inbox (
            id INTEGER PRIMARY KEY, chat INTEGER NOT NULL, message INTEGER NOT NULL,
            text TEXT NOT NULL, received INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            reply TEXT, thread TEXT, sent_message INTEGER);
        ''')

    def offset(self):
        return self.db.execute('SELECT value FROM cursor WHERE id=1').fetchone()[0]

    def ingest(self, updates, allowed):
        accepted = 0
        with self.db:
            for update in updates:
                uid = update['update_id']
                if uid < self.offset():
                    continue
                message = update.get('message', {})
                sender = message.get('from', {})
                chat = message.get('chat', {})
                if (chat.get('type') == 'private' and not sender.get('is_bot')
                        and sender.get('id') in allowed and chat.get('id') == sender.get('id')):
                    text = message.get('text', '[Вложение: первый прототип принимает только текст.]')[:4096]
                    result = self.db.execute('INSERT OR IGNORE INTO inbox(id,chat,message,text,received) VALUES(?,?,?,?,?)',
                                             (uid, chat['id'], message['message_id'], text, int(time.time())))
                    accepted += result.rowcount
                self.db.execute('UPDATE cursor SET value=max(value,?) WHERE id=1', (uid + 1,))
        return accepted

    def pending(self):
        return [dict(r) for r in self.db.execute("SELECT id,text,received FROM inbox WHERE status='pending' ORDER BY id LIMIT 20")]

    def acknowledge(self, uid, thread):
        with self.db:
            return self.db.execute("UPDATE inbox SET status='ready',reply=?,thread=? WHERE id=? AND status='pending'",
                                   (ACK, thread, uid)).rowcount

    def flush(self, api, allowed):
        # Persist 'sending' before HTTP. A timeout/crash may occur after Telegram
        # accepted a message, so uncertain sends MUST NOT be retried automatically.
        with self.db:
            self.db.execute("UPDATE inbox SET status='uncertain' WHERE status='sending'")
        rows = self.db.execute("SELECT * FROM inbox WHERE status='ready' ORDER BY id LIMIT 20").fetchall()
        sent = 0
        for row in rows:
            if row['chat'] not in allowed:
                continue
            with self.db:
                self.db.execute("UPDATE inbox SET status='sending' WHERE id=?", (row['id'],))
            try:
                response = api.call('sendMessage', chat_id=row['chat'], text=row['reply'],
                                    reply_parameters={'message_id': row['message']})
                message_id = response['message_id']
            except (BridgeError, KeyError, TypeError):
                with self.db:
                    self.db.execute("UPDATE inbox SET status='uncertain' WHERE id=?", (row['id'],))
                raise BridgeError('Доставка ответа не подтверждена. Автоповтора не будет; проверьте Telegram.') from None
            with self.db:
                self.db.execute("UPDATE inbox SET status='sent',sent_message=? WHERE id=?", (message_id,row['id']))
            sent += 1
        return sent


def bind_usernames(config, updates):
    """Resolve owner-approved usernames only from authenticated Bot API senders.

    Consume each name on first binding: later username reassignment cannot
    silently authorize a different numeric account.
    """
    changed = False
    for update in updates:
        message = update.get('message', {})
        sender = message.get('from', {})
        chat = message.get('chat', {})
        name = sender.get('username', '').lower()
        if (name in config.get('pending_usernames', [])
                and chat.get('type') == 'private' and not sender.get('is_bot')
                and isinstance(sender.get('id'), int) and sender['id'] > 0
                and chat.get('id') == sender['id']):
            if sender['id'] not in config['allowed']:
                config['allowed'].append(sender['id'])
            config['pending_usernames'].remove(name)
            config.setdefault('username_bindings', {})[name] = sender['id']
            changed = True
    return changed


def check_bot(api, progress=None):
    if progress: progress('Проверяю токен через Telegram…')
    bot = api.call('getMe')
    if progress: progress('Токен принят. Проверяю webhook…')
    if api.call('getWebhookInfo').get('url'):
        raise BridgeError('У бота уже есть webhook. Используйте отдельного бота; webhook не изменён.')
    return bot


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('setup'); setup.add_argument('--thread', required=True)
    setup.add_argument('--env-file', type=Path)
    sub.add_parser('pair')
    allow = sub.add_parser('allow-usernames'); allow.add_argument('names', nargs='+')
    sub.add_parser('tick')
    sub.add_parser('pending')
    sub.add_parser('status')
    ack = sub.add_parser('ack'); ack.add_argument('id', type=int); ack.add_argument('--thread', required=True)
    args = parser.parse_args()
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    if args.command == 'setup':
        if (state / 'config.json').exists():
            raise BridgeError('Настройка уже существует; не перезаписываю её.')
        token_file = (args.env_file or state / '.env').resolve()
        api = Telegram(read_token(token_file))
        bot = check_bot(api, lambda text: print(text, flush=True))
        save_config(state, {'token_file':str(token_file),'thread':args.thread,'allowed':[],'bot':bot['username']})
        print('Бот проверен. Теперь выполните pair и откройте выданную ссылку в своём Telegram.')
        return
    config = load_config(state)
    queue = Queue(state)
    if args.command == 'pending':
        print(json.dumps({'source':'external_telegram_untrusted','messages':queue.pending()}, ensure_ascii=False))
        return
    if args.command == 'status':
        print(json.dumps({'paired_users':len(config['allowed']), 'thread':config['thread'],
                          'counts':dict(queue.db.execute('SELECT status,count(*) FROM inbox GROUP BY status').fetchall())},ensure_ascii=False))
        return
    if args.command == 'ack':
        if args.thread != config['thread']:
            raise BridgeError('Другая задача: ответ не создан.')
        print(json.dumps({'queued_replies':queue.acknowledge(args.id,args.thread)}))
        return
    if args.command == 'allow-usernames':
        names = [n.lstrip('@').lower() for n in args.names]
        if any(not re.fullmatch(r'[a-z0-9_]{5,32}', n) for n in names):
            raise BridgeError('Некорректный Telegram username.')
        with exclusive(state):
            config = load_config(state)
            pending = config.setdefault('pending_usernames', [])
            for name in names:
                if name not in config.get('username_bindings', {}) and name not in pending:
                    pending.append(name)
            save_config(state, config)
        print(json.dumps({'pending_usernames':pending}, ensure_ascii=False))
        return
    api = Telegram(read_token(Path(config['token_file'])))
    with exclusive(state):
        config = load_config(state)
        if args.command == 'pair':
            check_bot(api, lambda text: print(text, flush=True))
            nonce = secrets.token_urlsafe(24)
            print('Откройте эту одноразовую ссылку в Telegram и нажмите Start (действует 5 минут):',flush=True)
            print('https://t.me/' + config['bot'] + '?start=' + nonce,flush=True)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                updates = api.call('getUpdates',offset=queue.offset(),timeout=20,allowed_updates=['message'])
                for update in updates:
                    m=update.get('message',{}); sender=m.get('from',{}); chat=m.get('chat',{})
                    if (m.get('text') == '/start ' + nonce and chat.get('type') == 'private'
                            and chat.get('id') == sender.get('id') and not sender.get('is_bot')):
                        if sender['id'] not in config['allowed']:
                            config['allowed'].append(sender['id'])
                        save_config(state,config)
                        queue.ingest(updates,config['allowed'])
                        print('Пользователь добавлен. Отправьте боту слово «тест».')
                        return
                queue.ingest(updates,config['allowed'])
            raise BridgeError('Время привязки истекло. Выполните pair повторно.')
        # One bounded poll per heartbeat; no background server or open TCP port.
        updates=api.call('getUpdates',offset=queue.offset(),timeout=0,allowed_updates=['message'])
        if bind_usernames(config, updates):
            save_config(state, config)
        accepted=queue.ingest(updates,config['allowed'])
        sent=queue.flush(api,config['allowed'])
        print(json.dumps({'accepted':accepted,'sent':sent}))


if __name__ == '__main__':
    try:
        main()
    except BridgeError as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:
        # Never print an urllib traceback: it may contain a token-bearing URL.
        print('Локальная ошибка: '+type(error).__name__,file=sys.stderr)
        sys.exit(1)
