# Установка с нуля (macOS + Yandex Cloud VM)

Это новая отдельная установка, не обновление работающей. Нужны Python 3.12+,
Node.js 22, Git, SSH, настроенный `yc`, каталог Yandex Cloud с оплатой ресурсов
и установленный/авторизованный Codex desktop с хотя бы одним проектом и задачей.
Чтение внутреннего каталога desktop поддерживает конкретную структуру данных:
при неизвестном формате синхронизация останавливается. Windows/Linux-сборщики
не проверены; установщик пользовательских служб рассчитан на macOS.

Это руководство описывает вариант с API Gateway. Для собственного HTTPS-домена
и Docker Compose используйте [контейнерное развёртывание](docker.md). Входящих соединений к компьютеру
нет, но содержимое задач доступно доверенным устройствам. Разрешение организации
на передачу рабочих данных нужно получить отдельно.

## 1. Исходники и окружение

```sh
git clone git@github.com:astgln/codex-workspace.git
cd codex-workspace
python3 -m venv .venv
.venv/bin/pip install ".[agent,relay,dev]"
export PATH="$PWD/.venv/bin:$PATH"
export CODEX_WORKSPACE_SOURCE="$PWD"
export CODEX_WORKSPACE_STATE="$HOME/.local/state/codex-workspace"
npm ci --prefix web --ignore-scripts
npm --prefix web run build
```

`main` — однопользовательская версия. Выбранный каталог состояния ещё не должен
существовать. Для экспериментальной установки используйте отдельный checkout,
окружение и состояние; у `setup` укажите `--branch experimental/multi-user`.
Не используйте одну очередь/ключи для двух установок.

## 2. HTTPS endpoint

В консоли Yandex Cloud создайте API Gateway в выбранном каталоге с временной
статической спецификацией из [примера](../examples/gateway-bootstrap.yaml).
Он пока возвращает только сообщение о незавершённой настройке. Сохраните ID
каталога, ID Gateway и его HTTPS-домен. Вход через Telegram не нужен.

```sh
codex-workspace setup --target yandex --folder YOUR_FOLDER_ID --gateway YOUR_GATEWAY_ID \
  --origin https://YOUR_GATEWAY_DOMAIN.apigw.yandexcloud.net
```

Команда создаёт приватный каталог 0700, транспортный ключ, закрытые настройки,
пустой начальный каталог задач, vault, recovery-пакет/код, публичный pin и
обязательный локальный E2EE-режим. Секреты не печатаются. Повтор поверх любого
существующего каталога запрещён. При сбое не удаляйте частичный vault вслепую:
сначала установите причину; действующие установки этой командой не исправляют.

Сохраните `recovery.json` и `recovery-code.txt` раздельно в защищённых хранилищах
за пределами компьютера. Вместе они дают доступ к ключам. Не коммитьте каталог
состояния, не присылайте файлы в задачи или issues. Примеры полей настройки —
[examples](../examples/README.md); рабочие значения генерирует `setup`.

## 3. VM и публикация

Идентификатор `project` создаёт `setup`; это ID области установки, а не ID
проекта в Codex. Читайте из настройки только это несекретное поле:

```sh
CATALOG_ID=$(python3 -c 'import json,os,pathlib; print(json.loads((pathlib.Path(os.environ["CODEX_WORKSPACE_STATE"])/"deployment.json").read_text())["project"])')
codex-workspace provision --folder YOUR_FOLDER_ID --project "$CATALOG_ID" \
  --owner owner --ssh-source YOUR_PUBLIC_ADMIN_IPV4
codex-workspace deploy publish
codex-workspace deploy cutover
```

`provision` создаёт платные VM/диск/сеть и ограничивает SSH указанным IPv4 /32.
`publish` требует чистую закоммиченную ветку, переносит по SSH только исходники,
сборку UI и серверные настройки без приватных ключей. На новой VM закрепляются
публичная authority и E2EE-режим. Существующую базу без E2EE установщик не
переключает автоматически. `cutover` заменяет временный ответ Gateway приложением.
Не запускайте `fresh_encryption --discard-old-web-content` для новой установки.

Подробности host key, сети, systemd и обновлений — [deployment](deployment.md).
Проверьте открытие сайта и `/health`; это ещё не проверка работы Codex.

## 4. Первое устройство и две службы

В первом терминале запустите:

```sh
codex-workspace devices pair --catalog "$CODEX_WORKSPACE_STATE/history-catalog.json" \
  --link-file "$CODEX_WORKSPACE_STATE/pair.html"
```

Во втором терминале откройте `open "$CODEX_WORKSPACE_STATE/pair.html"` и нажмите
Pair this device, затем «Привязать». Первая команда ждёт до 10 минут, сама доставит
подписанный реестр и удалит временную страницу после завершения. Ждите сообщения
«Ключи проверены и сохранены». Никому не пересылайте секрет ссылки.

Укажите реальный путь установленного CLI (не скачивайте второй Codex ради запуска):

```sh
CODEX_BIN=/absolute/path/to/codex
codex-workspace service install --kind requests --codex "$CODEX_BIN" \
  --catalog "$CODEX_WORKSPACE_STATE/history-catalog.json"
codex-workspace service install --kind history --codex "$CODEX_BIN" \
  --catalog "$CODEX_WORKSPACE_STATE/history-catalog.json"
launchctl print "gui/$(id -u)/net.codex-workspace.requests"
launchctl print "gui/$(id -u)/net.codex-workspace.history"
```

Каталог автоматически заполнится проектами desktop. Откройте сайт и задачу,
проверьте историю, отправьте «Ответь SETUP OK, не используй инструменты».
Подтверждение установки — полученный ответ, а не одна лишь запущенная служба.
Занятая desktop задача может ждать writer lock; не удаляйте блокировки вручную.
Safari и установленную PWA нужно привязать отдельно. Уведомления включаются
внутри PWA. Восстановление и отзыв — [device login](device-login.md).

## Проверка без облака

`tests/integration/test_fresh_install.py` создаёт новое состояние без `.local`,
инициализирует ключи, привязывает первое синтетическое устройство, проверяет
подписанный вход и обмен зашифрованным содержимым. Это не проверка создания
новых облачных ресурсов или реального iPhone. Ни пользовательские ключи, ни
локальный каталог Codex в тесте не используются.
