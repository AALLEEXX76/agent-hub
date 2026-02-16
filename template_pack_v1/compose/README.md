## Compose notes (Template Pack v1)

- Copy `.env.example` to `.env` on the target server and fill values.
- `Caddyfile` uses `{$SITE_DOMAIN}` from env.
- Referral Service is included in the same stack (referral-api + postgres).

MVP TODO (we will implement later):
- replace `ghcr.io/yourorg/referral-api:latest` with real image/build
- add healthchecks
- add backup job hooks (DB dump + wp-content archive)
