# Docker Compose: собственный сервер с HTTPS

Контейнер содержит relay и собранный веб/PWA-интерфейс. На ноутбуке остаются
нативные службы запросов и истории, существующий Codex и приватные ключи.
Нужны Docker Engine с Compose на сервере, домен с DNS на этот сервер и доступные
порты 80/443 для автоматического HTTPS. Уже настроенный reverse proxy тоже подходит.
Yandex Cloud и Telegram не требуются.

## 1. Настройка на ноутбуке

Установите Python 3.12+ и локальный пакет из выбранного checkout:

```sh
python3 -m venv .venv
.venv/bin/pip install ".[agent]"
export PATH="$PWD/.venv/bin:$PATH"
export CODEX_WORKSPACE_STATE="$HOME/.local/state/codex-workspace"
codex-workspace setup --target docker --origin https://workspace.example.org
```

Укажите свой точный HTTPS origin без завершающего `/`. Каталог состояния должен
быть новым: команда откажется перезаписывать существующие ключи или настройки.
Для экспериментальной установки добавьте `--branch experimental/multi-user` и
используйте ту же ветку на сервере. Не меняйте origin работающего пространства:
он входит в подписи и доверие устройств.

Сохраните `recovery.json` и `recovery-code.txt` раздельно вне компьютера.
На сервер передаются **только** два файла из подкаталога `relay/`:
`relay.json` и `compose.env`. В них публичная authority, ID установки, origin
и SHA-256 транспортного ключа. Сам bearer, vault, recovery и каталог задач
остаются на ноутбуке. `relay.json` имеет права 0644 для чтения непривилегированным
контейнером; родительский каталог — 0700. Никогда не копируйте весь каталог состояния.

## 2. Запуск сервера

Клонируйте репозиторий на сервер, переключитесь на ту же ветку. Передайте
`relay.json` и `compose.env` через SCP в корень клона (эти имена исключены из Git).
Содержимое конфигурации не вставляйте в командную строку.

```sh
docker compose --env-file compose.env --profile https up -d --build --wait
docker compose --env-file compose.env ps
```

Caddy получает и продлевает сертификат для `WORKSPACE_ORIGIN`; его хранилище тоже
постоянное. DNS и внешний firewall нужно настроить до запуска. `/health` проверяет
relay, но не доказывает успешный TLS или исполнение задачи; проверьте сайт по HTTPS.
Не публикуйте HTTP relay напрямую в интернет.

Если HTTPS уже обслуживает другой proxy, запускайте без профиля:

```sh
docker compose --env-file compose.env up -d --build --wait
```

Proxy должен передавать запросы на `127.0.0.1:8080`, сохраняя Origin и Cookie,
без кеширования API/HTML и без записи тел запросов/Authorization/Cookie в логи.
Порт можно задать в `compose.env`: `WORKSPACE_PORT=8081`.
Свой публичный origin всё равно должен совпадать с `setup`.
Конфигурацию из другого каталога можно выбрать через `WORKSPACE_RELAY_CONFIG`.

## 3. Первый браузер и службы

На ноутбуке выполните команду, оставив её работать:

```sh
codex-workspace devices pair --catalog "$CODEX_WORKSPACE_STATE/history-catalog.json" \
  --link-file "$CODEX_WORKSPACE_STATE/pair.html"
```

В другом терминале: `open "$CODEX_WORKSPACE_STATE/pair.html"`. Нажмите Pair this
device, затем «Привязать» на сайте. Ссылка одноразовая, действует 10 минут.
Дождитесь сообщения «Ключи проверены и сохранены».

Затем установите обе пользовательские службы macOS:

```sh
CODEX_BIN=/absolute/path/to/your/installed/codex
codex-workspace service install --kind requests --codex "$CODEX_BIN" \
  --catalog "$CODEX_WORKSPACE_STATE/history-catalog.json"
codex-workspace service install --kind history --codex "$CODEX_BIN" \
  --catalog "$CODEX_WORKSPACE_STATE/history-catalog.json"
```

Проверьте историю и ответ на тестовый запрос с сайта. Desktop writer lock может
задержать выполнение; блокировки не удаляют вручную. Для телефона Safari и PWA
привязываются отдельно. Детали — [авторизация](device-login.md) и
[службы](collector-routing.md).

## Обновление и сохранность данных

`workspace-data` хранит SQLite, режим E2EE, публичный корень, подписанный реестр,
зашифрованные записи и ключ VAPID. Пересоздание контейнера сохраняет этот volume.
Имя Compose-проекта должно оставаться прежним: запускайте команды из того же
каталога либо задайте постоянный `COMPOSE_PROJECT_NAME` в `compose.env`.
Не выполняйте `down -v` на рабочей установке.

Перед обновлением остановите relay и сделайте приватную копию его volume.
Обычный `docker compose ... stop relay` не удаляет данные. Затем:

```sh
git pull --ff-only
docker compose --env-file compose.env --profile https up -d --build --wait
```

При изменении схемы контейнер предварительно создаёт согласованную SQLite-копию
и проверяет миграцию. Копии остаются в `migration-backups` внутри volume; храните
последнюю проверенную копию до проверки обновления и удаляйте старые по своей
политике хранения. Это не заменяет внешнюю резервную копию volume.
Откат на несовместимую схему запрещён; для восстановления используйте совместимый
образ и проверенную копию, а не старый бинарник поверх новой базы.
Не масштабируйте relay до нескольких реплик: используется SQLite и один worker.
Смена публичного ключа, origin или установки для того же volume останавливает запуск.

Работающий deployment в Yandex Cloud не мигрирует автоматически. Его перенос
требует отдельного согласованного переключения с сохранением ключей и базы.

## Сборка и ограничения

[Многоэтапная сборка](https://docs.docker.com/build/building/multi-stage/)
собирает UI и Python отдельно; `.dockerignore` допускает только исходники сборки.
Ни `.local`, ни Git, ни recovery в build context не передаются. Relay работает
как UID 10001 с read-only корневой ФС, без Linux capabilities; записывает только
volume и ограниченный `/tmp`. Healthcheck обнаруживает сбой; Docker restart policy
перезапускает завершившийся процесс, но не перезапускает живой unhealthy контейнер.
HTTPS-профиль использует [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
Компрометация самого веб-клиента остаётся ограничением E2EE.

## Воспроизводимая проверка

После установки `.[agent,dev]` выполните `bash tests/containers/run.sh` из корня
checkout. Скрипт соберёт образ, создаст отдельные временные ключи и volumes,
проверит HTTPS с доверенным только в тестовом процессе CA, первое устройство,
вход, CSRF, E2EE и сохранность данных при пересоздании контейнеров. Затем удалит
только созданный им Compose-проект и временные данные. Порты теста по умолчанию
18443/18081; `TEST_TLS_PORT`/`TEST_RELAY_PORT` позволяют выбрать свободные.
Он не подключается к рабочему Codex и не исполняет задачи. Та же проверка есть в CI.
