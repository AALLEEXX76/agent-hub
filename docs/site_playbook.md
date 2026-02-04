# Site Playbook (MVP)

Цель: управлять сайтами предсказуемо через human-команды (status/list/up/down/block/unblock/init), с безопасными гейтами и проверками (HTTP + docker + route).

## Модель сайта (как у нас сейчас)

- Каждый сайт = docker-compose проект (контейнер `<name>-web-1`) на localhost порт `1808x`.
- Доступ снаружи через Caddy route: `https://ii-bot-nout.ru/<name>/` -> `127.0.0.1:<port>`.
- Состояния:
  - up + route present -> HTTP 200
  - up + route absent -> HTTP 404
  - down + route present -> HTTP 502
  - down + route absent -> HTTP 404

## Команды (human)

### 1) Список сайтов
- `site: list`
  - делает: docker_status -> находит контейнеры `*-web-1` -> HTTP HEAD на `/<name>/`
  - ожидаем: список `sites[]` с http_code/state/route

### 2) Статус одного сайта
- `site: status name=<site>`
  - ожидаем: `site status OK (up=True route=present http=200)` или FAIL с причиной

### 3) Block / Unblock (route)
- `site: block name=<site> confirm=ROUTE_<SITE>`
- `site: unblock name=<site> confirm=ROUTE_<SITE>`
  - меняет только Caddy route
  - требует confirm токен

### 4) Up / Down (docker compose)
- `site: up name=<site> confirm=UP_<SITE>`
- `site: down name=<site> confirm=DOWN_<SITE>`
  - вызывает compose_up/compose_down
  - гейты: `ALLOW_DANGEROUS=1` + confirm токен

### 5) Инициализация нового сайта
- `site: init name=<site> port=<port> domain=<domain> confirm=INIT_<SITE>`
  - создаёт папку, compose, env, index.html
  - затем обычно: `site: up ...` и `site: unblock ...`

## Гейты и безопасность

- status/list: SAFE (без confirm)
- block/unblock: требует confirm токен
- up/down/init: требует `ALLOW_DANGEROUS=1` + confirm токен

## Definition of Done (MVP)

1) `tools/test_e2e.sh` проходит (RC=0).
2) `site: status` корректно различает 200/404/502 и пишет понятный итог.
3) `site: down` без block даёт 502, с block даёт 404, `site: up` возвращает 200.
