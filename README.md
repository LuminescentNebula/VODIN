# VODIN

Сервис для обнаружения клиентов в локальной сети с динамическими IP и синхронизации с Veyon.

## Что реализовано

- **Клиент**:
  - поднимает HTTP API (`/info`, `/master/announce`) на фиксированном порту `8765`;
  - отдает JSON с `room`, `hostname`, `veyon-version`, `iat` (если время аренды неизвестно — `null`), `ip`;
  - определяет версию Veyon автоматически через `veyon-cli --version`;
  - принимает подтверждение мастера по подписи Ed25519;
  - хранит подтвержденный `master_url` локально;
  - отслеживает изменение IP и отправляет обновление мастеру на `/client/update`.

- **Мастер**:
  - сканирует подсеть, привязанную к **названию сети** (не к имени интерфейса);
  - ищет клиентов по `GET /info` на порту `8765`;
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
```

### `master.yml`

```yaml
network_name: "school-lan"
named_networks:
  school-lan: "192.168.10.0/24"
master_private_key_path: "keys/master_private.pem"
clients_store_path: "data/clients.json"
master_port: 9876
scan_timeout: 0.8
veyon_update_command: "veyon-cli networkobjects import --json '{clients_json}'"
```

## Запуск

Клиент:

```bash
vodin client --config client.yml --host 0.0.0.0
```

Мастер:

```bash
vodin master --config master.yml --host 0.0.0.0 --port 9876
```

Повторный поиск клиентов:

```bash
curl -X POST http://127.0.0.1:9876/scan
```

## Автозапуск при старте ОС

- Linux: systemd unit для команды `vodin client --config client.yml`
- Windows: Task Scheduler/NSSM service для `vodin client --config client.yml`
