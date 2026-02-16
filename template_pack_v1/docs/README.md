# Template Pack v1 (WordPress+WooCommerce)

Структура:
- compose/  — docker-compose.yml + .env.example
- caddy/    — Caddyfile template
- wp-content/ — theme + plugins (referral-connector, age-gate, seo, consent, etc.)
- seed/     — стартовые страницы/категории/товары (MVP)
- docs/     — спецификация и заметки

MVP цель: собрать "золотой образ" магазина (WP+Woo) + Referral Service (referral-api+postgres) в том же compose.
