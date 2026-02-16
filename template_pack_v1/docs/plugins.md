# WP plugins/components — choices (Template Pack v1)

Цель: зафиксировать *чем именно* реализуем то, что уже зафиксировано в правилах/спеке.

## Уже зафиксировано (точно)
- SEO: **Yoast SEO**
- Referral Connector: **наш плагин** `referral-connector` (по спекам M/L)
- AgeGate: **наш плагин** `age-gate` (sitewide + remember=forever + toggle)

## Нужно выбрать (TBD, но уже зарезервировано место)
### Cookie consent (режим 1A + блокировка тегов до согласия)
- Требования: кнопки Accept / Deny / Customize, категории Necessary/Analytics/Marketing, совместимость с GTM Consent Mode.
- Выбор плагина: **Complianz — GDPR/CCPA Cookie Consent** (поддержка Consent Mode, категории cookies)

### GTM внедрение
- Требования: поддержка Consent Mode, удобная вставка контейнера.
- Выбор: **Google Tag Manager for WordPress (GTM4WP)**

### GA4 + Яндекс.Метрика (через GTM)
- Реализация: через GTM теги, запуск только после согласия.
- Плагины: не обязательны (можно без), но слот “через GTM” фиксируем.

### 2FA для WP админов
- Требования: TOTP (Google Authenticator), включаем для админов.
- Выбор плагина: TBD

### Лог входов/действий в WP админке
- Требования: audit/admin activity log (входы/изменения критичных настроек).
- Выбор плагина: TBD

### Оплата: Yandex Pay / Split
- Выбор плагина: TBD

### Доставка
- СДЭК: плагин TBD
- Почта России: плагин TBD

## Примечание
Пока не выбрали конкретные плагины (TBD) — агент в Template Pack кладёт *слоты* и включает/настраивает их, когда выбор зафиксируем.
