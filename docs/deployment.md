# Развёртывание

Используйте отдельные checkout, конфигурацию и базу для каждой ветки.
Действующая установка Yandex Cloud закреплена за `experimental/multi-user`.
`main` — отдельная однопользовательская сборка со schema 4; не публикуйте её
поверх экспериментальной установки без отдельного решения о переходе.

## Сервер

Нужны VM Ubuntu, сервисный аккаунт с доступом только к нужному Lockbox secret,
API Gateway с публичным HTTPS и закрытая сеть Gateway → VM:8080.
SSH ограничивается проверенным административным IPv4 /32. Скрипты не изменяют VPN.

Секрет `TELEGRAM_BOT_TOKEN` хранится в Lockbox. Закрытая локальная конфигурация
`.local/deployment.json` содержит IDs ресурсов, `folder`, `project` (ID области
каталога), `settings.owner`, `secret`, `client_hash`, `url`, `vm_instance`,
`vm_public_ip`, `vm_private_ip`, `vm_network`, `gateway`, `release_branch`.
Значение клиентского ключа в этот JSON не помещается.
Существующие ресурсы импортируйте по проверенным ID; не угадывайте VM по SSH alias.

```sh
python3 deploy_vm.py --folder FOLDER_ID --project CATALOG_ID \
  --owner TELEGRAM_USERNAME --ssh-source ADMIN_IPV4
npm ci --prefix web --ignore-scripts
npm --prefix web run build
python3 release_vm.py publish
```

`deploy_vm.py` требует заранее заданного `secret` в deployment.json. Это
инструмент VM provisioning, а не автоматическое создание Telegram-бота и Lockbox.
Для отдельной разрешённой сети можно явно указать `--ssh-interface en0` у
`release_vm.py publish`. Интерфейс должен уже существовать; маршруты не меняются.

SSH host key берётся из аутентифицированного Compute API, проверка host key
обязательна. Артефакт передаётся SCP и сверяется по SHA-256. Установщик получает
секрет из Lockbox, выполняет резервное копирование SQLite и репетицию миграции,
затем переключает `/opt/codex-workspace/current` и перезапускает `codex-workspace`.
Проверка `/health` по SSH подтверждает доступность процесса, а не вход пользователя.

Для нового Gateway выполните `python3 release_vm.py cutover` после проверки VM.
В BotFather зарегистрируйте точный HTTPS origin для Telegram Login. Корневой URL
сайта работает без специальных query-параметров. Серверу передаются
`OWNER_USERNAME`, `TELEGRAM_BOT_TOKEN`, `CLIENT_KEY_HASH`, `PROJECT_ID`,
`PUBLIC_ORIGIN`. Конфигурация `/etc/codex-workspace/config.json` закрыта для чтения
посторонним. Секреты не включаются в Git, cloud-init или argv.

## Компьютер с Codex

Файл `.local/web.json` содержит `url`, `key_file` и `paused`; `key_file` указывает
на файл 0600 с `BRIDGE_CLIENT_KEY`. Каталог проектов задаётся отдельно.
Сохраните конфигурацию приватно; не копируйте её в сообщения или отчёты.

```sh
python3 web_client.py catalog /absolute/path/to/catalog.json
python3 install_cli_service.py --codex /absolute/path/to/codex \
  --catalog /absolute/path/to/catalog.json
python3 history_watch.py --catalog /absolute/path/to/catalog.json
```

История должна работать отдельной пользовательской службой с закрытыми логами.
Установщик запросов отказывается перезаписывать существующий launchd job.
При переносе существующей службы сначала дождитесь отсутствия выполняемого
запроса, остановите прежний job и обновите пути. Не запускайте два обработчика
одной очереди. Каталог и очередь сохраняются при переносе checkout.

## PWA и уведомления

На iPhone: Safari → Поделиться → На экран «Домой». Откройте установленное
приложение и явно включите уведомления (iOS 16.4+). VAPID-ключ создаётся в закрытом
серверном каталоге и должен сохраняться между релизами. Push содержит название
задачи и сокращённый ответ. Неопределённая отправка автоматически не повторяется.

## Восстановление

Перед релизом создаётся согласованная приватная копия SQLite. Для отката на
старую схему остановите сервис и восстановите совместимую проверенную копию
в отдельный путь. Не запускайте старый код поверх новой схемы и не удаляйте
локальную очередь для повтора неопределённого запроса. Процедуры сверки —
в [описании локальных служб](collector-routing.md).

Публикация проверяет текущую ветку по `release_branch` и требует закоммиченные
исходники. В артефакте `release.json` записываются ветка и точный commit.

## Локальная раскладка checkout

Основной checkout: `~/Projects/codex-workspace` (`main`). Экспериментальная
ветка — зарегистрированный Git worktree внутри него:
`~/Projects/codex-workspace/worktrees/experimental` (`experimental/multi-user`).
Каталог `/worktrees/` исключён из Git основного checkout. Для нового клона:

```sh
git worktree add worktrees/experimental experimental/multi-user
```

Действующая серверная конфигурация, локальная очередь и пути фоновых служб
относятся к экспериментальному worktree. В основной ветке не хранится вторая
копия активной очереди. Не запускайте оба checkout на одной серверной базе.
