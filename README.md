# VODIN

Сервис для обнаружения клиентов в локальной сети с динамическими IP и синхронизации с Veyon.

## Что реализовано

- **Клиент**:
  - поднимает HTTP API (`/info`, `/master/announce`) на порту `client_port` из конфигурации;
  - bind'ится на IP интерфейса выбранной сети (`find_interface_for_network(resolve_network_by_name(...))`), если не задан `--host`;
  - отдает JSON с `room`, `hostname`, `veyon-version`, `exp` (best-effort: Linux через `nmcli`, Windows через PowerShell/WMI DHCP lease; если недоступно — `default_lease_ttl_seconds`, иначе `null`), `ip`;
  - определяет версию Veyon автоматически через `veyon-cli --version`;
  - принимает подтверждение мастера по подписи Ed25519;
  - хранит подтвержденный `master_url` локально;
  - отслеживает изменение IP и отправляет обновление мастеру на `/client/update`.

- **Мастер**:
  - сканирует подсеть, привязанную к **названию сети** (не к имени интерфейса);
  - ищет клиентов по `GET /info` на порту `client_port` из конфигурации мастера;
  - подтверждает себя найденным клиентам через подпись;
  - хранит клиентов в JSON-хранилище;
  - имеет endpoint `/scan` для повторного поиска по команде;
  - при смене IP клиента запускает команду обновления Veyon (через шаблон).

## Установка

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e .
```

## CLI

- Универсальный режим: `vodin <command> ...`
- Основные команды:
  - `vodin client --config client.yml`
  - `vodin master --config master.yml`
  - `vodin client-install-autostart --config client.yml`
  - `vodin client-autostart-status`
  - `vodin client-uninstall-autostart`
- Отдельные entrypoint'ы:
  - `vodin-client --config client.yml`
  - `vodin-master --config master.yml`

## Генерация ключей Ed25519

```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

priv = Ed25519PrivateKey.generate()
pub = priv.public_key()

open("master_private.pem", "wb").write(
    priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
)
open("master_public.pem", "wb").write(
    pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)
```

Для клиента используйте отдельную пару ключей.

## Раздельные конфигурации

Нужно использовать **два разных файла конфигурации**: один для клиента, второй для мастера.

### `client.yml`

```yaml
room: "Аудитория-101"
network_name: "school-lan"
named_networks:
  school-lan: "192.168.10.0/24"
master_public_key_path: "keys/master_public.pem"
client_private_key_path: "keys/client_private.pem"
state_path: "data/client_state.json"
watchdog_interval_seconds: 15
client_port: 8765
default_lease_ttl_seconds: 3600  # fallback при недоступном lease из ОС
```

### `master.yml`

```yaml
network_name: "school-lan"
named_networks:
  school-lan: "192.168.10.0/24"
master_private_key_path: "keys/master_private.pem"
clients_store_path: "data/clients.json"
master_port: 9876
client_port: 8765
scan_timeout: 0.8
veyon_update_command: 'veyon-cli networkobjects import {clients_file} format "%location%;%name%;%host%"'
veyon_cleanup_command: ""  # опционально: команда очистки ранее импортированных объектов перед новым импортом
```

`{clients_file}` — временный CSV-файл, который мастер генерирует перед импортом в формате `%location%;%name%;%host%` (room, hostname, ip).


Шаблоны также лежат в `release/templates/client.template.yml` и `release/templates/master.template.yml`.

## Сборка релизов (раздельно для ролей)

Используется скрипт `scripts/build_release.py` (PyInstaller + Linux single-file Python build).

```bash
pip install pyinstaller
python scripts/build_release.py --role client --clean --onefile
# ВАЖНО: --clean удаляет предыдущие артефакты (включая dist/vodin-client)
python scripts/build_release.py --role master --onefile

# Linux: единый Python-файл
python scripts/build_release.py --role client --clean --linux-single-py
python scripts/build_release.py --role master --linux-single-py
```

Результат:

- `dist/vodin-client/` — бинарник клиента + шаблон `client.yml`
- `dist/vodin-master/` — бинарник мастера + шаблон `master.yml`
- `dist/vodin-client-linux-py/vodin-client-linux.py` — единый Python-файл для Linux + шаблон `client.yml`
- `dist/vodin-master-linux-py/vodin-master-linux.py` — единый Python-файл для Linux + шаблон `master.yml`

Для onedir-сборки просто уберите `--onefile`.

Для Linux single-file варианта используйте `--linux-single-py` (требуется установленный Python и зависимости в системе).

Примечание: lease определяется кроссплатформенно (Linux: `nmcli`, Windows: PowerShell/WMI). На Windows скрипт забирает raw `DHCPLeaseExpires` и парсит его в приложении, чтобы избежать ошибок вида `ToDateTime(...): dmtfDate вне диапазона`. Если источник lease недоступен, используется fallback `default_lease_ttl_seconds`.

## Запуск

Клиент:

```bash
vodin client --config client.yml
# или
vodin-client --config client.yml

# По умолчанию клиент bind'ится на IP интерфейса, найденного для `network_name`/`named_networks`.
# Ручное переопределение при необходимости:
vodin client --config client.yml --host 0.0.0.0
```

Мастер:

```bash
vodin master --config master.yml --host 0.0.0.0 --port 9876
# или
vodin-master --config master.yml
```

Повторный поиск клиентов:

```bash
curl -X POST http://127.0.0.1:9876/scan
```

## Автозапуск при старте ОС

Рекомендуемый способ — использовать встроенные CLI-команды:

```bash
# Установка автозапуска клиента
vodin client-install-autostart --config client.yml

# Проверка статуса
vodin client-autostart-status

# Удаление автозапуска
vodin client-uninstall-autostart
```

Поддерживаются платформы:

- **Linux**: генерируется и устанавливается systemd unit (по умолчанию `vodin-client.service` в `/etc/systemd/system`).
- **Windows**: создается Scheduled Task (по умолчанию `VODIN Client`) с запуском при старте системы от `SYSTEM`.

Можно переопределить имя unit/task через `--name`:

```bash
vodin client-install-autostart --config client.yml --name vodin-room101.service
vodin client-autostart-status --name vodin-room101.service
vodin client-uninstall-autostart --name vodin-room101.service
```

> На Linux команды требуют прав на запись в `/etc/systemd/system` и вызов `systemctl` (обычно через `sudo`).

### Windows (NSSM, альтернатива)

```powershell
nssm install VODINClient "C:\VODIN\vodin-client.exe" "--config C:\VODIN\client.yml"
nssm set VODINClient Start SERVICE_AUTO_START
nssm start VODINClient
```
