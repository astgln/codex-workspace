# Codex Workspace

Репозиторий: [astgln/codex-workspace](https://github.com/astgln/codex-workspace).

Личное веб-приложение для работы с существующими задачами Codex на вашем компьютере.
Вход по ключу доверенного устройства, проекты и история переписки, файлы, ход выполнения, недельная
квота и PWA с уведомлениями об ответах.

`main` — однопользовательская версия. Сервер принимает только один настроенный
аккаунт владельца; сообщения сразу поступают в очередь локального Codex.
Экспериментальная разработка ведётся отдельно в `experimental/multi-user`.
Текущая установка в Yandex Cloud использует эту ветку, а не `main`.

## Устройство

Браузер/PWA → HTTPS API Gateway → FastAPI на VM → SQLite.
На компьютере две службы исходящими HTTPS-запросами получают работу и публикуют
историю. Выполнение использует `codex exec resume` в исходной задаче с её правами.
Входящие соединения к компьютеру и управляющий чат не требуются.

- [Установка с нуля](docs/installation.md)
- [Архитектура и поток данных](docs/architecture.md)
- [Развёртывание и обновление](docs/deployment.md)
- [Локальные службы и восстановление](docs/collector-routing.md)
- [Безопасность](docs/security.md)

## Разработка

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[agent,relay,dev]"
CODEX_WORKSPACE_SOURCE="$PWD" .venv/bin/python -m unittest discover -s tests -t . -q
npm ci --prefix web --ignore-scripts
npm --prefix web run build
cd web && npx playwright install chromium && npx playwright test
```

Интерфейс React/TypeScript использует компоненты LuSeptem/codex-webui.
Лицензия исходных компонентов сохранена в [web/licenses/codex-webui-MIT.txt](web/licenses/codex-webui-MIT.txt).

Вход и привязка устройств описаны в [руководстве авторизации](docs/device-login.md).

Собственный код распространяется по [MIT](LICENSE). Сообщения об уязвимостях —
по [SECURITY.md](SECURITY.md). Проверки перед публикацией — [public release](docs/public-release.md).
