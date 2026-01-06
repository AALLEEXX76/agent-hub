2026-01-06: compose_logs включён end-to-end (Brain→webhook→iibotv2). n8n workflow XC7hfkwDAPoa2t9L allowlist расширен: compose_logs; workflow publish; n8n restart.
2026-01-06: compose_ps проверен end-to-end (Brain→webhook→iibotv2), /opt/n8n показывает n8n+postgres Up.
2026-01-06: n8n deploy без рестарта: Public API PUT /workflows/{id} + POST /activate работает (XC7hfkwDAPoa2t9L). Используем artifacts/*.put_min.json.
