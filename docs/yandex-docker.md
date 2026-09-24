# Docker на Yandex VM за API Gateway

Это продолжение **шагов 0–3** [полной установки](installation.md): CLI, Gateway,
локальные ключи и новая VM уже созданы через `setup --target yandex` и `provision`,
но `deploy publish` ещё **не запускался**. Выполняйте команды из того же Bash-сеанса
на Mac, в корне checkout. Здесь HTTPS предоставляет Gateway; Caddy и свой домен
не нужны. Это инструкция новой установки, не перенос работающего сервера.

## 1. Аутентифицированный SSH

Загрузите только публичный host key из Compute API и закрепите его для точного
IP созданной VM. Не используйте `ssh-keyscan` как доказательство подлинности:

```sh
python3 - <<'PY'
import json,os,re,subprocess
from pathlib import Path
state=Path(os.environ['CODEX_WORKSPACE_STATE'])
d=json.loads((state/'deployment.json').read_text())
r=subprocess.run(['yc','compute','instance','get-serial-port-output',d['vm_instance'],
    '--folder-id',d['folder'],'--format','json'],capture_output=True,text=True,timeout=45)
if r.returncode:raise SystemExit('Compute API unavailable; retry after VM startup')
keys=re.findall(r'(ssh-ed25519 [A-Za-z0-9+/=]+)',json.loads(r.stdout)['contents'])
if not keys:raise SystemExit('Host key not yet published; wait for cloud-init and retry')
value=d['vm_public_ip']+' '+keys[-1]+'\n'
p=state/'vm-known-hosts'
if p.exists() or p.is_symlink():
    if p.is_symlink() or p.read_text()!=value:raise SystemExit('Host key changed; stop and investigate')
else:
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(value)
print('SSH host key pinned')
PY
CW_VM_IP=$(python3 -c 'import json,os,pathlib; print(json.loads((pathlib.Path(os.environ["CODEX_WORKSPACE_STATE"])/"deployment.json").read_text())["vm_public_ip"])')
CW_SSH=(-i "$CODEX_WORKSPACE_STATE/web-vm-ed25519" -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$CODEX_WORKSPACE_STATE/vm-known-hosts" \
  -o ConnectTimeout=15)
ssh "${CW_SSH[@]}" "bridge@$CW_VM_IP" 'sudo cloud-init status --wait'
```

При таймауте проверьте адрес /32, заданный при provision. Проверку host key не
отключайте. Явную привязку к интерфейсу при необходимости добавьте в `CW_SSH`
как `-o BindInterface=ИМЯ`, только для уже настроенного разрешённого маршрута.

## 2. Docker Engine на новой Ubuntu VM

Команды по [официальному apt-способу Docker](https://docs.docker.com/engine/install/ubuntu/).
На этой VM не должно быть другого deployment или конфликтующего Docker-пакета:

```sh
ssh "${CW_SSH[@]}" "bridge@$CW_VM_IP" 'sudo bash -s' <<'REMOTE'
set -euo pipefail
if systemctl is-active --quiet codex-workspace; then
  echo 'Existing native deployment: stop and plan migration separately'; exit 1
fi
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl --fail --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
cat > /etc/apt/sources.list.d/docker.sources <<APT
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
APT
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
REMOTE
```

Пользователь `bridge` не добавляется в группу docker; административные команды
выполняются через sudo. Облачная security group остаётся границей входа на 8080:
не открывайте этот порт для `0.0.0.0/0`. Правила UFW сами по себе не заменяют её.

## 3. Только серверные настройки и исходники

Сформируйте серверную конфигурацию из уже созданного состояния. Новые ключи
**не генерируются**. Исходники берутся из текущего коммита; приватные файлы и
история Git не входят в архив:

```sh
test -z "$(git status --porcelain --untracked-files=no)"
python3 - <<'PY'
import json,os
from pathlib import Path
from codex_workspace.devices.e2ee_admin import write_private
state=Path(os.environ['CODEX_WORKSPACE_STATE'])
d=json.loads((state/'deployment.json').read_text())
export=state/'docker-export'
export.mkdir(mode=0o700)  # refuse an existing export; never overwrite keys/state
config={'OWNER_USERNAME':d['settings']['owner'],'CLIENT_KEY_HASH':d['client_hash'],
        'PROJECT_ID':d['project'],'PUBLIC_ORIGIN':d['url'],
        'auth_pin':json.loads((state/'device-auth.json').read_text())}
write_private(export/'relay.json',json.dumps(config)+'\n')
(export/'relay.json').chmod(0o644)
write_private(export/'compose.env','WORKSPACE_ORIGIN='+d['url']+'\nCOMPOSE_PROJECT_NAME=codex-workspace\n')
PY
git archive --format=tar.gz --output "$CODEX_WORKSPACE_STATE/docker-export/source.tar.gz" HEAD
chmod 600 "$CODEX_WORKSPACE_STATE/docker-export/source.tar.gz"
CW_ARCHIVE_SHA=$(shasum -a 256 "$CODEX_WORKSPACE_STATE/docker-export/source.tar.gz" | cut -d ' ' -f 1)
ssh "${CW_SSH[@]}" "bridge@$CW_VM_IP" 'mkdir -m 700 workspace-upload'
scp "${CW_SSH[@]}" "$CODEX_WORKSPACE_STATE/docker-export/"{source.tar.gz,relay.json,compose.env} \
  "bridge@$CW_VM_IP:workspace-upload/"
ssh "${CW_SSH[@]}" "bridge@$CW_VM_IP" \
  "printf '%s  %s\n' '$CW_ARCHIVE_SHA' workspace-upload/source.tar.gz | sha256sum --check"
```

Если доставка прервалась, продолжайте с существующими проверенными export/upload,
а не повторяйте их создание. Не загружайте `web.json`, bearer, vault, recovery или
весь каталог состояния. Для другой установки нужен другой сервер/каталог/volume.

## 4. Compose и маршрут Gateway

Gateway соединяется с приватным адресом VM, поэтому нужен отдельный override
публикации порта. Доступ извне ограничивает созданная cloud security group.

```sh
ssh "${CW_SSH[@]}" "bridge@$CW_VM_IP" 'sudo bash -s' <<'REMOTE'
set -euo pipefail
mkdir -m 700 /opt/codex-workspace-docker
cd /opt/codex-workspace-docker
tar -xzf /home/bridge/workspace-upload/source.tar.gz --no-same-owner
install -m 644 /home/bridge/workspace-upload/relay.json relay.json
install -m 600 /home/bridge/workspace-upload/compose.env compose.env
cat > compose.yandex.yaml <<'YAML'
services:
  relay:
    ports: !override ['8080:8080']
YAML
docker compose --env-file compose.env -f compose.yaml -f compose.yandex.yaml up -d --build --wait --wait-timeout 120
curl --fail --show-error http://127.0.0.1:8080/health
rm /home/bridge/workspace-upload/source.tar.gz /home/bridge/workspace-upload/relay.json /home/bridge/workspace-upload/compose.env
rmdir /home/bridge/workspace-upload
REMOTE
codex-workspace deploy cutover
curl --fail --show-error "$CW_ORIGIN/health"
open "$CW_ORIGIN"
```

Теперь вернитесь к **шагу 4** [общей инструкции](installation.md): привяжите
первый браузер и запустите обе локальные службы. На этом этапе ключи и cookies
не печатайте в терминал для диагностики.

## Проверка и обновления

```sh
ssh "${CW_SSH[@]}" "bridge@$CW_VM_IP" \
  'sudo bash -c "cd /opt/codex-workspace-docker && docker compose --env-file compose.env -f compose.yaml -f compose.yandex.yaml ps"'
curl --fail --show-error "$CW_ORIGIN/health"
```

Нативный `deploy publish` для этой VM больше не используйте: он установит systemd
сервис на том же порту. Для обновления сначала сохраните резервную копию volume,
затем доставьте новый `git archive` тем же SCP с проверкой SHA-256 и распакуйте
в существующий `/opt/codex-workspace-docker`. `relay.json`, `compose.env`, override
и volume сохраняются. Запустите ту же команду Compose `up -d --build --wait`.
Не выполняйте `down -v`. Подробности сохранности и миграций — [Docker](docker.md).

Сценарий проверен по исходникам, синтаксису команд и локальному контейнерному
тесту. Создание новой платной VM, внешняя сеть и конкретные права вашего облака
не проверяются этими тестами; успешный `/health` ещё не доказывает ответ Codex.
