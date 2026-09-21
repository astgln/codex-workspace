# Развёртывание отдельного веб-приложения

## Компоненты

Небольшая выделенная VM Ubuntu, отдельная сеть и группа безопасности,
Lockbox для Telegram-токена. VM получает только
доступ на чтение своего секрета. API Gateway сохраняет
публичный HTTPS-адрес и направляет запросы на порт 8080 по внутренней сети.
Прямой публичный доступ к приложению закрыт группой безопасности.

На VM работают один процесс Uvicorn, SQLite в режиме WAL. Установка и обновления выполняются по SSH/SCP. Путь данных: `/var/lib/codex-workspace`; конфигурация с
токеном: `/etc/codex-workspace/config.json` (root:service, 0640).
Данные и конфигурация отделены от каталога релиза.

## Установка и обновление

`deploy_vm.py` использует авторизованный `yc` и локальный checkpoint прежнего
развёртывания `.local/deployment.json`. Ресурсы создаются в явно указанном
каталоге. Имя проекта, владелец и разрешённые пользователи не меняются
неявно. Скрипт не меняет профиль `yc`, VPN, DNS или настройки Codex.

```sh
python3 deploy_vm.py --folder YOUR_FOLDER --thread BRIDGE_THREAD \
  --project WARCRAFT_PROJECT --owner OWNER --allowed OWNER MEMBER \
  --ssh-source SSH_EGRESS_IPV4
npm ci --prefix web --ignore-scripts
npm --prefix web run build
python3 release_vm.py publish
python3 release_vm.py probe
```

Первый перенос существующего mailbox с Cloud Functions выполняется через
`release_vm.py publish --initial-migration`. На время снимка запись в прежний
веб-API замораживается. Экспорт доступен только через закрытую IAM-функцию;
содержимое не выводится в терминал или задачу. Начальное состояние импортируется
только при отсутствии SQLite, последующие релизы его не перезаписывают.

После ответа `/vm-health` с `mode=standalone-web`:

```sh
python3 release_vm.py cutover
```

Сборка передаётся по SCP, установка и проверка `/health` выполняются по SSH.
Ключ хоста берётся из аутентифицированного вывода загрузки Compute API;
StrictHostKeyChecking включён. На VM проверяется SHA-256 полученного архива.
Публикация использует обычные SSH/SCP-соединения без локального управляющего сокета.
Начальная настройка VM устанавливает Python и SSH-ключ, но не запускает
загрузку приложения из хранилища. Старый экспериментальный таймер установки
отключается при первом развёртывании по SSH.

Токен извлекается из Lockbox внутри VM и не передаётся через shell-аргументы.
Исходящий адрес SSH должен соответствовать облачной группе безопасности;
смена адреса VPN требует обновления точного `/32` правила. Более широкий
диапазон не включается автоматически. Скрипт не меняет сеть ноутбука.

`--recreate-empty` допустим только для первоначальной VM, на которую приложение
ещё не установлено. Он не является механизмом обновления работающей системы.

## Вход

В BotFather → Login Widget зарегистрируйте точный HTTPS origin сайта.
Используется popup-поток Telegram Login (`post_message`) с подписанным ответом
Login Widget (также поддерживается подписанный OIDC ID token). Это вход на обычный
сайт; Telegram Mini App и обмен authorization code с Client Secret не требуются. URL явно содержит `origin`: текущая
официальная JS-библиотека пропускает его, а сервер Telegram возвращает `origin required`.
Обработчик принимает результат только с origin Telegram и из открытого им окна;
затем сервер проверяет подпись. OIDC-токен должен содержать одноразовый nonce.
В живом окружении Telegram также возвращает объект Login Widget с `hash`.
Он проверяется по [официальной схеме HMAC](https://core.telegram.org/widgets/login-legacy):
ключ — SHA-256 токена бота, подписываются все полученные поля кроме `hash`.
Принимаются ответы не старше пяти минут; сервер атомарно погашает challenge и
подписанное подтверждение, не позволяя повторить его с новым challenge.
Widget не содержит подписанного nonce, поэтому его replay-проверка отдельная.
Ни один формат не принимается без своей криптографической проверки. Ключи получаются только с
фиксированного официального JWKS endpoint с проверкой TLS.

Сервер обновляет публичные ключи раз в час. При сетевой недоступности свежий
кеш может доставить доверенный локальный сборщик через защищённый API.
Это дополнительное полномочие сборщика: его ключ должен храниться как секрет.
Кеш старше 24 часов не используется; неизвестный ключ и неподтверждённая подпись
не дают вход. После проверки Telegram сервер выдаёт случайную непрозрачную сессию
в cookie `__Host-workspace-session` с Secure, HttpOnly, SameSite=Lax и Path=/.
В SQLite хранится SHA-256 идентификатора, срок и отдельный CSRF-токен.
JavaScript не получает идентификатор сессии. POST-запросы требуют точного
`PUBLIC_ORIGIN` и CSRF-токена; выход отзывает сессию на сервере. Сессия действует
восемь часов и восстанавливается после обновления страницы.

`PUBLIC_ORIGIN` задаётся при SSH-развёртывании из HTTPS URL приложения.
Корневой URL работает без query-параметров: `v=widget-login` использовался только
для обхода старого кэша. HTML и ответы авторизации имеют `Cache-Control: no-store`.

Владелец входит первым, участник — со своего аккаунта. После первого входа
участника владелец выдаёт ему доступ на странице «Доступ к тредам».
Авторизация участника сама по себе не открывает ни одного треда.

## Локальный сборщик и передача в Codex

Настройки: `.local/web.json` с `url`, `project_id`, `key_file`, `paused`.
Клиентский ключ хранится отдельно в файле 0600. На сервере — только его SHA-256.
Каталог содержит точные ID проектов и задач из приложения; локальные пути
не определяют принадлежность проекту. Постоянные локальные службы запросов
и истории работают автономно и независимо. Доставка использует `codex exec
resume` с исходными правами задачи; desktop сохраняет обычный режим.

Установка, состояния очереди, корреляция ответов и безопасное обновление:
[collector-routing.md](collector-routing.md). Ручная передача из управляющей
задачи и общий App Server не входят в рабочую архитектуру.

## Эксплуатационные ограничения

Одна VM — одна точка отказа. SQLite и файлы не имеют высокой доступности;
перед использованием для важных данных настройте отдельные резервные копии.
200 запросов и 100 МБ вложений — ограничения маленького приватного проекта,
а не архитектура публичного сервиса. Сборщик требует включённого ноутбука, установленного и авторизованного CLI и сети.
При неоднозначной отправке требуется ручная сверка marker в целевой задаче.

После проверки переноса старые Cloud Functions, YDB, бакет прежнего
развёртывания и служебные аккаунты serverless-схемы удалены. Перед удалением
состояние прежней пустой очереди сохранено в закрытом локальном архиве.
Рабочие VM, диск, сеть, адреса, API Gateway, Lockbox и аккаунт VM сохранены.
Старый `deploy.py` запрещает serverless-развёртывание после переноса на VM;
обновления выполняются только через `release_vm.py publish`. Таймеры
и Telegram webhook не нужны веб-приложению. Публичный IP VM и диск продолжают
участвовать в тарификации согласно правилам Yandex Cloud.

При split tunneling проверяйте исходящий IP именно SSH (например, первое поле `$SSH_CONNECTION` на доступном сервере). HTTPS-сервисы определения IP могут показывать другой маршрут. `--ssh-source` принимает один IPv4 и разрешает только `/32`.

## Installed app and Web Push

The site includes a Web App Manifest, home-screen icons and a root service
worker. It deliberately does not cache conversations, attachments or API data.
On iOS/iPadOS 16.4+, open in Safari, choose Share → Add to Home Screen, launch
that installed app, sign in and enable notifications under “Приложение и
уведомления”. Permission is requested only from that button's click. The same
panel can disable the current device; signing out removes its subscription.

The VM generates its VAPID private key once in the protected service data
directory (`vapid.pem`, mode 0600); releases preserve it. Do not rotate it during
normal deployment: subscriptions depend on its public key. No Apple Developer
membership or Telegram messages are required for Web Push.

A server loop checks every 10 seconds for approval requests (owner only) and
completed answers (participants with current task access). Active-task public
final answers arrive via the local history collector; request results can also
arrive via the existing result API. Old history is not replayed as notifications.
Push endpoints and encryption keys stay in the private SQLite database. Only
Apple, Google and Mozilla push service endpoints are accepted; redirects are
not followed. Notifications contain generic text, not conversation contents.
Opening one still requires a valid website session and current task access.

Delivery commits attempt intent before network I/O. An uncertain result or crash
after intent is not retried automatically; it can therefore miss a notification.
Explicit retryable provider responses use bounded backoff, and expired
subscriptions are removed. History and request publications share turn identity
to avoid duplicate answer notifications when both report the same turn. Provider acceptance is not proof of delivery to a phone. Test
actual installed iOS delivery separately, including when the app is closed.

Для явно разрешённого подключения через отдельный существующий интерфейс можно
использовать `python3 release_vm.py publish --ssh-interface en0` (имя интерфейса
нужно проверить на своей машине). Параметр передаёт `BindInterface` одинаково в
SSH и SCP; VPN, таблица маршрутов и конфигурация SSH не изменяются. Правило SSH
на VM должно разрешать подтверждённый исходящий адрес этого соединения `/32`.
Параметр не изменяет облачные правила автоматически и не отключает проверку
ключа сервера.
