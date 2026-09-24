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

## 0. Подготовка компьютера и облака

Все команды ниже выполняются **на Mac**, в одном Bash-сеансе, если явно не указано
иначе. Сценарий создаёт новую установку и платные ресурсы. Для работающего сервера
не повторяйте `setup` и создание ресурсов: используйте раздел обновления ниже.
Сначала создайте облако/платёжный аккаунт в [консоли](https://console.yandex.cloud/)
и привяжите оплату. Авторизация в браузере и оплата остаются действиями владельца.

Нужны права создавать каталог, сеть/подсети/security group, VM/диск, сервисный
аккаунт и Gateway, а также назначать сервисный аккаунт VM. Выполняйте сценарий
учётной записью владельца личного облака либо попросите администратора выдать эти
права в выделенном каталоге. При PermissionDenied остановитесь; не расширяйте роли
работающих сервисов. Каталог ниже выделенный: provision использует фиксированные
имена ресурсов `codex-workspace` и не должен встречать чужие одноимённые ресурсы.

При установленном Homebrew:

```sh
bash
set -euo pipefail
brew install python@3.12 node@22 git
export PATH="$(brew --prefix python@3.12)/libexec/bin:$(brew --prefix node@22)/bin:$PATH"
python3 --version
node --version
```

Если Homebrew отсутствует, сначала установите его по [официальной инструкции](https://brew.sh/).
Установка и настройка Yandex CLI ([документация](https://yandex.cloud/en/docs/cli/quickstart)):

```sh
if ! command -v yc >/dev/null 2>&1; then
  cw_installer=$(mktemp)
  curl --fail --location https://storage.yandexcloud.net/yandexcloud-yc/install.sh -o "$cw_installer"
  bash "$cw_installer"
  rm "$cw_installer"
fi
export PATH="$HOME/yandex-cloud/bin:$PATH"
yc version
yc config profile create codex-workspace
yc init
```

В мастере выберите профиль `codex-workspace`, войдите в браузере и выберите личное
облако с оплатой. Если профиль уже есть, активируйте его командой
`yc config profile activate codex-workspace` вместо повторного `create`.
Не выводите `yc config list`: в некоторых профилях он содержит приватный ключ.
Создайте отдельный каталог и сохраните его ID:

```sh
CW_CLOUD_ID=$(yc config get cloud-id)
CW_FOLDER_ID=$(yc resource-manager folder create --cloud-id "$CW_CLOUD_ID" \
  --name codex-workspace --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
yc config set folder-id "$CW_FOLDER_ID"
yc resource-manager folder get "$CW_FOLDER_ID" --format json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["id"],d["name"])'
```

При продолжении после закрытия терминала не создавайте каталог заново:
`CW_FOLDER_ID=$(yc config get folder-id)` после активации того же профиля.

## 1. Исходники и окружение

```sh
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
CW_BRANCH=main
# Для новой экспериментальной установки: CW_BRANCH=experimental/multi-user
git clone --branch "$CW_BRANCH" git@github.com:astgln/codex-workspace.git
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

SSH-доступ к GitHub должен быть настроен заранее; проверьте его через `ssh -T git@github.com`
(успешное приветствие GitHub может сопровождаться кодом выхода 1). Для выбора
экспериментальной ветки поменяйте `CW_BRANCH` **перед** клонированием.

## 2. HTTPS endpoint

Создайте API Gateway с временным статическим ответом. Домен и сертификат
предоставляет Gateway; собственный домен и Telegram не нужны.

```sh
CW_GATEWAY_ID=$(yc serverless api-gateway create --folder-id "$CW_FOLDER_ID" \
  --name codex-workspace --spec examples/gateway-bootstrap.yaml --no-logging \
  --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
CW_ORIGIN=$(yc serverless api-gateway get "$CW_GATEWAY_ID" --folder-id "$CW_FOLDER_ID" \
  --format json | python3 -c 'import json,sys; print("https://"+json.load(sys.stdin)["domain"])')
curl --fail --show-error "$CW_ORIGIN/"
```

Ожидается `Setup pending`. Если команда создания прервалась после успешного
создания ресурса, найдите его ID через `yc serverless api-gateway list --folder-id
"$CW_FOLDER_ID"`; не создавайте дубликат.

```sh
codex-workspace setup --target yandex --folder "$CW_FOLDER_ID" --gateway "$CW_GATEWAY_ID" \
  --origin "$CW_ORIGIN" --branch "$CW_BRANCH"
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
read -r -p "Публичный IPv4, с которого вы подключаетесь по SSH к VM: " CW_SSH_IPV4
codex-workspace provision --folder "$CW_FOLDER_ID" --project "$CATALOG_ID" \
  --owner owner --ssh-source "$CW_SSH_IPV4"
```

`provision` создаёт платные VM/диск/сеть и ограничивает SSH указанным IPv4 /32.
`publish` требует чистую закоммиченную ветку, переносит по SSH только исходники,
сборку UI и серверные настройки без приватных ключей. На новой VM закрепляются
публичная authority и E2EE-режим. Существующую базу без E2EE установщик не
переключает автоматически. `cutover` заменяет временный ответ Gateway приложением.
Не запускайте `fresh_encryption --discard-old-web-content` для новой установки.

Используется Ubuntu 24.04, 2 vCPU с гарантированной долей 20%, 2 GB RAM, SSD 20 GB,
публичный IPv4 и отдельная сеть. Точная стоимость зависит от тарифов и времени
работы. SSH открыт только с указанного /32, 8080 — только для Gateway.
При VPN адрес выхода HTTPS может отличаться от адреса SSH: не определяйте его
вслепую через произвольный сервис «мой IP». Используйте проверенный адрес маршрута.
[Сеть Gateway](https://yandex.cloud/en/docs/api-gateway/concepts/networking)
требует подсети во всех доступных зонах; provision создаёт их автоматически.

Дальше выберите **один** вариант. Для Docker выполните [раздел Docker на Yandex VM](yandex-docker.md),
затем вернитесь к шагу 4. Для нативного systemd-варианта продолжайте здесь:

```sh
codex-workspace deploy publish
codex-workspace deploy cutover
curl --fail --show-error "$CW_ORIGIN/health"
open "$CW_ORIGIN"
```

`publish` получает SSH host key через аутентифицированный Compute API, сверяет
архив и проверяет сервис по SSH. Первое подключение может потребовать ожидания
cloud-init; при временной ошибке повторите `publish`, не `setup`.
Не используйте `StrictHostKeyChecking=no`. `cutover` направляет Gateway на
приватный адрес VM. Ожидается `{"status":"ok","mode":"standalone-web"}`.
Это проверка сервера, а не выполнения задачи Codex.

Подробности host key, сети, systemd и обновлений — [deployment](deployment.md).

## 4. Первое устройство и две службы

В первом терминале запустите:

```sh
codex-workspace devices pair --catalog "$CODEX_WORKSPACE_STATE/history-catalog.json" \
  --link-file "$CODEX_WORKSPACE_STATE/pair.html"
```

Во втором терминале выполните `open "$HOME/.local/state/codex-workspace/pair.html"`
(для нестандартного состояния укажите выбранный путь) и нажмите
Pair this device, затем «Привязать». Первая команда ждёт до 10 минут, сама доставит
подписанный реестр и удалит временную страницу после завершения. Ждите сообщения
«Ключи проверены и сохранены». Никому не пересылайте секрет ссылки.

Укажите реальный путь установленного CLI (не скачивайте второй Codex ради запуска):

```sh
# Укажите существующий бинарник установленного приложения, например:
CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex
test -x "$CODEX_BIN"
"$CODEX_BIN" --version
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

## 5. Повторный вход в терминал и проверка сервера

Укажите прежний checkout и состояние, не создавайте их заново:

```sh
cd "$HOME/Projects/codex-workspace" # замените на путь своего клона
export PATH="$PWD/.venv/bin:$HOME/yandex-cloud/bin:$PATH"
export CODEX_WORKSPACE_SOURCE="$PWD"
export CODEX_WORKSPACE_STATE="$HOME/.local/state/codex-workspace"
yc config profile activate codex-workspace
CW_FOLDER_ID=$(yc config get folder-id)
CW_ORIGIN=$(python3 -c 'import json,os,pathlib; print(json.loads((pathlib.Path(os.environ["CODEX_WORKSPACE_STATE"])/"web.json").read_text())["url"])')
CW_VM_IP=$(python3 -c 'import json,os,pathlib; print(json.loads((pathlib.Path(os.environ["CODEX_WORKSPACE_STATE"])/"deployment.json").read_text())["vm_public_ip"])')
CW_SSH=(-i "$CODEX_WORKSPACE_STATE/web-vm-ed25519" -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$CODEX_WORKSPACE_STATE/vm-known-hosts" \
  -o ConnectTimeout=15)
```

После успешного нативного `publish` host key уже закреплён. Проверка по SSH:

```sh
ssh "${CW_SSH[@]}" "bridge@$CW_VM_IP" \
  'systemctl is-active codex-workspace; curl --fail --silent http://127.0.0.1:8080/health'
curl --fail --show-error "$CW_ORIGIN/health"
```

Не выкладывайте необработанные логи, конфигурацию или содержимое состояния в issues.
Для Docker проверяйте `docker compose ... ps`, как описано в отдельном разделе.

## 6. Обновление нативного сервера

```sh
git pull --ff-only
npm ci --prefix web --ignore-scripts
npm --prefix web run build
codex-workspace deploy publish
curl --fail --show-error "$CW_ORIGIN/health"
```

Не пересоздавайте Gateway, VM и ключи. При обновлении локального Python-пакета
сначала завершите активные запросы и остановите только соответствующие сборщики;
процедура — [локальные службы](collector-routing.md). Обновление сервера не
требует перезапуска desktop. Docker обновляется по своей инструкции.

## 7. Частые остановки

| Симптом | Что проверить |
| --- | --- |
| PermissionDenied у `yc` | Аккаунт, профиль, выбранный каталог и выданные роли |
| Недоступна зона/квота | Квоты Compute/VPC и доступность зон; не запускайте повторный setup |
| SSH timeout | Публичный IPv4 /32 именно маршрута SSH, security group, завершение cloud-init |
| Нет host key | Дождитесь загрузки VM, повторите publish; не обходите проверку ключа |
| Gateway 502/504 | Сервис/контейнер на 8080, приватный адрес VM, привязку Gateway к сети |
| Нужен ключ устройства | Привяжите браузер; Safari и PWA имеют разные хранилища |
| Нет истории | Оба launchd job, совместимость каталога desktop, состояние E2EE |
| Запрос ждёт | Writer lock или отсутствующие исходные права задачи; не удаляйте lock/очередь |

Остановка VM не удаляет диск и другие платные ресурсы. Удаление установки —
отдельная операция после проверки резервных копий и принадлежности всех ресурсов;
в этом руководстве команды массового удаления намеренно отсутствуют.

## Проверка без облака

`tests/integration/test_fresh_install.py` создаёт новое состояние без `.local`,
инициализирует ключи, привязывает первое синтетическое устройство, проверяет
подписанный вход и обмен зашифрованным содержимым. Это не проверка создания
новых облачных ресурсов или реального iPhone. Ни пользовательские ключи, ни
локальный каталог Codex в тесте не используются.
