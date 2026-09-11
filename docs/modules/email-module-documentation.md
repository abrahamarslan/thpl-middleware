# Email Module — `app/modules/emails/`

Reusable transactional-email layer for `th-middleware`. Resend is the default
provider, but no caller ever knows that: features hand a provider-neutral
message to a factory, and delivery, retries, template rendering, provenance and
analytics are owned by this module.

> **Doctrine in one line:** *compose → persist → queue → send → track*. The
> database row is always the source of truth for an email's state; the provider
> is a swappable detail behind a registry.

---

## 1. Why it is shaped this way

| Concern | Decision | Reason |
|---|---|---|
| Provider | `provider.py` registry + `get_email_provider()` | Swapping/adding a provider is one registration, never a branch in callers. The lazy factory is the single test patch point. |
| Content | `templates.py` registry + Jinja2 files | Features pass a template *name* + context, never an HTML string. A new email is a new registry entry. |
| Persistence | `emails` row written **before** any HTTP call | The API answers instantly; the worker owns slow I/O and retries survive a crash. |
| Lifecycle | `emails.status` + `email_events` timeline | Provider webhooks build delivered → opened → clicked / bounced; unknown events are acknowledged, never retried. |
| Provenance | `actor_id` / `source_ip` / `request_id` on `emails` | Answers *who queued it, from where, when* — the sender-side half of "when/where". |
| Analytics | `/api/emails/stats` + CDC on `email_events`/`email_links` | Aggregates stay in Postgres; the event stream flows to ClickHouse/Grafana. Message bodies are deliberately **not** CDC'd. |
| Attachments | Existing `documents` module | One source of file truth — an invoice PDF is referenced, never duplicated. |

---

## 2. File map

| File | Responsibility |
|---|---|
| `__init__.py` | Module doctrine + layer overview. |
| `provider.py` | `OutboundEmail`, `EmailAttachment`, `ProviderResult`, `EmailProvider` protocol, `ResendProvider`, `register_provider()`, `build_provider()`, `get_email_provider()`, `EmailProviderError`. |
| `templates.py` | `EmailTemplate`, `register_template()`, `render_email()`, `RenderedEmail`, `TemplateNotFoundError`, `TemplateContextError`; the template registry (per-module directories + required-context validation). |
| `templates/` | Default template root. **Feature modules own their templates** — auth templates live in `app/modules/users/templates/` (`_base.en.html` + `<name>.<locale>.html`/`.txt`). |
| `model.py` | `Email`, `EmailEvent`, `EmailLink` (SQLAlchemy 2.0). |
| `schema.py` | `EmailCreate`, `EmailTemplateSend`, `EmailOut` (fat), `EmailSlimOut` (list), `EmailEventOut`, `EmailStatsOut`, `EmailAttachmentMeta`. |
| `crud.py` | `create_email`, `get_email`, `get_by_provider_message_id`, `list_emails` (slim `load_only`), `email_stats`. |
| `service.py` | `compose_and_queue_email`, `send_template_email`, `get_email_stats`, `get_email`, `verify_resend_signature`, `process_resend_webhook`. |
| `api.py` | HTTP surface (see §7). |
| `app/tasks/emails.py` | `send_email` Celery task — attachment loading, provider call, retry accounting, kill switches. Queue: `integrations`. |

---

## 3. Data model

### `emails` (one row per outbound message)

- **Identity**: `id` (bigint PK), `uuid` (public).
- **Subject link**: `emailable_type` / `emailable_id` (polymorphic — the email *about* a User, Invoice, …).
- **Recipients** (JSONB arrays): `email_to`, `email_cc`, `email_bcc`, and `all_recipients` (deduped union → "ever emailed x@y?" via JSONB containment).
- **Sender**: `email_from`, `email_from_name`, `reply_to`, `return_path`.
- **Content**: `subject`, `preheader`, `body_text`, `body_html`, `body_type`.
- **Template**: `template_id`, `template_name`, `template_data` (JSONB render context), `locale`.
- **Source**: `campaign_id`, `batch_id`, `metadata` (mapped as Python `metadata_`).
- **Provenance**: `actor_id` (who queued), `source_ip`, `request_id`, `user_agent`.
- **Status**: `status`, `status_message`, `error_message`, `status_history` (rolling JSONB journal, capped 50).
- **Retries**: `attempts`, `max_attempts`.
- **Provider**: `provider`, `provider_message_id`, `provider_response` (JSONB).
- **Timestamps**: `scheduled_at`, `sent_at`, `delivered_at`, `failed_at`, `first/last_opened_at`, `first_clicked_at`.
- **Metrics**: `open_count`, `click_count`, `bounce_type` (`soft`/`hard`), `spam_score`.
- Mixins: `IntPKMixin`, `TimestampMixin`, `SoftDeleteFilteredMixin`, `HasDocumentsMixin`, `HasTagsMixin`.
- Extra index `ix_emails_created_at` (time-window stats/list filters).

**Status machine:** `pending → processing → sent → delivered` with `bounced` /
`failed` terminals and `suppressed` when outbound is disabled. Transitions are
applied via `Email.push_status(...)`, which appends to `status_history`.

### `email_events` (provider webhook timeline)

`email_id` FK, `event_type` (`email.delivered|opened|clicked|bounced|complained|delivery_delayed`),
`event_at`, `ip_address`, `user_agent`, `url` (clicks), `location`,
`provider_event_id`, `provider_data` (raw JSONB). Relationship:
`Email.events` (`selectinload`).

### `email_links` (per-link click aggregates)

`email_id` FK, `original_url`, `link_hash`, `click_count`, `unique_clicks`,
`first/last_clicked_at`. Relationship: `Email.links` (`selectinload`).

---

## 4. The reusable send paths

### 4.1 Compose raw content — `service.compose_and_queue_email`

```python
email = await compose_and_queue_email(
    db,
    EmailCreate(to=["a@b.co"], subject="Hi", body_html="<b>hi</b>"),
    actor_id=user.id,
)
```

Persists (`status="pending"`), attaches documents, records an `email_queued`
activity, captures provenance from request context, then hands off to Celery.

### 4.2 Send a template — `service.send_template_email` (preferred)

```python
await send_template_email(
    db,
    "password_reset_code",
    to=[user.email],
    context={"name": user.name, "code": "4821", "expires_minutes": 10},
    emailable_type="User",
    emailable_id=str(user.id),
)
```

Renders the registered template and delegates to `compose_and_queue_email`.
**Feature code should always use this** — it never hand-builds HTML.

### 4.3 Provider adapter — `provider.py`

```python
from app.modules.emails.provider import OutboundEmail, EmailAttachment, get_email_provider

result = await get_email_provider().send(OutboundEmail(
    to=["a@b.co"], subject="Hi", sender="Tarrina <noreply@ab.co>",
    html="<b>hi</b>",
    attachments=[EmailAttachment(filename="x.pdf", content=raw_bytes)],
))
result.provider_message_id  # -> stored on the row
```

**Adding a provider** (e.g. Postmark) is two lines plus a class:

```python
class PostmarkProvider:
    name = "postmark"
    async def send(self, message: OutboundEmail) -> ProviderResult: ...

register_provider("postmark", lambda: PostmarkProvider(...))
```

Select it with `EMAIL_PROVIDER=postmark`. No caller changes.

### 4.4 Templates

A template is one `register_template(EmailTemplate(...))` entry whose `html`/
`text` are file *base names*, e.g. `password_reset_code` resolves
`password_reset_code.en.html` then `password_reset_code.<default>.html` then
`password_reset_code.html`. Global context (`company_name`, `support_email`,
`company_address`, `site_url`, `frontend_url`, `year`, `locale`) is injected
automatically; caller context wins.

**Per-module directories.** `EmailTemplate.directory` (default
`EMAIL_TEMPLATE_DIR`) lets each feature own its templates; the Jinja
`Environment` builds a `ChoiceLoader` across every registered directory. Auth,
for example, owns `app/modules/users/templates/`.

**Required context.** `EmailTemplate.required_context=(...)` makes rendering
raise `TemplateContextError` when a key is missing — a renamed template
variable becomes a loud failure at send time, not a blank email.

**Typed contexts.** Feature modules wrap the dict in a Pydantic model
(`app/modules/users/auth_emails.py` `BaseAuthEmailContext` and friends) so the
template contract is validated at the call site.

**Auth templates** (registered in `users/auth_emails.py`):
`welcome`, `login_otp`, `password_reset_code`, `password_reset_link`,
`password_changed`. They extend `users/templates/_base.en.html` (brand header +
footer + logo) and render a request-audit block (IP, device, GeoIP location,
timestamp).

---

## 5. Delivery, retries and kill switches — `app/tasks/emails.py`

`send_email(email_id)` (Celery, queue `integrations`, `max_retries=5`):

1. Guard: row absent → retry shortly (compose txn not yet visible); status not
   `pending`/`queued` → no-op.
2. `EMAIL_ENABLED=false` → mark `suppressed`, no network call.
3. Increment `attempts`, load attachments (local disk; S3 skipped loudly).
4. `EMAIL_LOG_ONLY=true` → mark `sent` without calling the provider (dev).
5. Call `get_email_provider().send(...)`; on success store provider id/response.
6. On failure: retry with exponential backoff (`EMAIL_RETRY_BASE_SECONDS * 2^n`,
   capped at `EMAIL_RETRY_MAX_BACKOFF_SECONDS`) until `max_attempts`, then
   `failed`. The row records the last error and its `status_history`.

Async-in-Celery follows the house pattern: `asyncio.run(work())` with a
throwaway `NullPool` engine.

---

## 6. Webhooks and analytics

- `POST /api/emails/webhooks/resend` — svix-signature verified when
  `RESEND_WEBHOOK_SECRET` is set; skipped (logged) otherwise for dev.
  Appends an `email_events` row and updates aggregates/status. Unknown message
  ids are acknowledged (`False`) so the provider never retry-storms us.
- `GET /api/emails/stats?date_from=&date_to=` — totals plus delivery/open/click
  rates over a window. Rates are `0.0` when the denominator is zero.
- `email_events` and `email_links` are in Debezium's `table.include.list`
  (`config/debezium/zoho-mirror-connector.json`) → Kafka → ClickHouse/Grafana.
  The `emails` table is intentionally excluded (bodies are not analytics data);
  per-event "when/where/who" lives in `email_events`.
- Real client IP is captured by `RequestContextMiddleware` (`X-Forwarded-For`
  first hop, else `X-Real-IP`, else socket peer) and stored as `source_ip`.

---

## 7. HTTP API

All routes are mounted at `/api/emails`; all except the webhook require a JWT.

| Method | Path | Returns | Notes |
|---|---|---|---|
| POST | `/send` | `202 EmailOut` | Compose raw and queue. |
| POST | `/send-template` | `202 EmailOut` | Render a registered template and queue. |
| GET | `/stats` | `EmailStatsOut` | Aggregates for `date_from`/`date_to`. |
| GET | `` (list) | `list[EmailSlimOut]` | Slim DTO; filters `status`, `recipient`, `emailable_type`, `emailable_id`, `template_name`, `date_from`, `date_to`, `page`, `page_size`. |
| GET | `/{email_id}` | `EmailOut` | Fat detail: documents + events. |
| POST | `/webhooks/resend` | `{"status": "received"}` | Unauthenticated; svix-verified. Hidden from schema. |

Provider payloads never reach the API layer — `OutboundEmail` is built in the
worker.

---

## 8. Configuration reference (`app/core/conf.py`)

| Env var | Default | Purpose |
|---|---|---|
| `EMAIL_PROVIDER` | `resend` | Adapter registry key. |
| `EMAIL_ENABLED` | `true` | Master outbound switch (off ⇒ `suppressed`). |
| `EMAIL_LOG_ONLY` | `false` | Dev: persist + mark sent without a provider call. |
| `RESEND_API_KEY` | `""` | Resend API key (required in prod). |
| `RESEND_API_URL` | `https://api.resend.com/emails` | Endpoint. |
| `RESEND_DEFAULT_FROM` | `Core Platform <noreply@example.com>` | Default sender. |
| `RESEND_DEFAULT_REPLY_TO` | `""` | Default reply-to. |
| `RESEND_WEBHOOK_SECRET` | `""` | svix signing secret (empty = skip verify, dev only). |
| `EMAIL_MAX_ATTEMPTS` | `3` | Per-row delivery attempts. |
| `EMAIL_RETRY_BASE_SECONDS` | `60` | Backoff base. |
| `EMAIL_RETRY_MAX_BACKOFF_SECONDS` | `900` | Backoff cap. |
| `EMAIL_TIMEOUT_SECONDS` | `30` | Provider HTTP timeout. |
| `EMAIL_TEMPLATE_DIR` | `app/modules/emails/templates` | Template root. |
| `EMAIL_DEFAULT_LOCALE` | `en` | Locale fallback. |
| `EMAIL_COMPANY_NAME` | `Tarrina Health` | Brand value in templates. |
| `EMAIL_SUPPORT_EMAIL` | `tech@tarrinahealth.com` | Support address in templates. |
| `EMAIL_SITE_URL` | `https://tarrinahealth.com` | Marketing/site base for footer links. |
| `EMAIL_COMPANY_ADDRESS` | iHub Gujarat address | Footer legal address. |
| `FRONTEND_URL` | `http://localhost:5173` | Base for action links (reset, dashboard). |
| `GEOIP_ENABLED` | `false` | Enable MaxMind lookups for audit location. |
| `GEOIP_CITY_DB_PATH` | `""` | Path to `GeoLite2-City.mmdb` (not bundled). |
| `GEOIP_COUNTRY_DB_PATH` | `""` | Path to `GeoLite2-Country.mmdb` fallback. |

Resend setup: create an API key, verify the sending domain, set
`RESEND_DEFAULT_FROM` to an address on it, and point a Resend webhook at
`https://<domain>/api/emails/webhooks/resend` with the signing secret copied to
`RESEND_WEBHOOK_SECRET`.

---

## 9. Consumers

The first consumers all live in the auth module and go through
`app/modules/users/auth_emails.py` (typed contexts → `send_template_email`):

- **Welcome** (`welcome`) on registration.
- **Login OTP** (`login_otp`) on `POST /api/auth/login-otp/request`; the code is
  exchanged for tokens at `POST /api/auth/login-otp/verify`.
- **Password reset** (`password_reset_code` / `password_reset_link`) — accepts a
  single `identifier` (email/username/phone), code HMAC-hashed in
  `password_reset_tokens`.
- **Password changed** (`password_changed`) on reset or change-password.

Reusable takeaways:

- Codes are stored HMAC-hashed; the email body necessarily contains the code,
  so its short TTL bounds exposure.
- Auth responses are uniform (`{sent: true}`) to avoid account enumeration.
- Because delivery goes through the template registry, features own no HTML and
  no provider code; each security email carries an IP/device/GeoIP audit block.

---

## 10. Operations

```bash
./manage.sh migrate              # b7c1f2a9d4e0 (provenance + reset cols) then d2e3f4a5b6c7 (login_otp_tokens)
./manage.sh register-debezium    # picks up email_events / email_links (initial snapshot)
```

1. Set `RESEND_API_KEY`, `RESEND_DEFAULT_FROM`, `RESEND_WEBHOOK_SECRET` and the
   brand/`FRONTEND_URL` values in `deployment/.env`.
2. Keep `RESEND_WEBHOOK_SECRET` set in production — without it the webhook
   signature check is skipped.
3. For audit location, drop a GeoLite2 `.mmdb` into `deployment/config/geoip/`
   and set `GEOIP_ENABLED=true` (see `config/geoip/README.md`).
4. `EMAIL_LOG_ONLY=true` on non-prod stacks lets you exercise the full flow
   without a provider key; inspect rows via `GET /api/emails` and `/stats`.

---

## 11. Testing

| Test | Layer | Covers |
|---|---|---|
| `tests/test_emails_templates.py` | hermetic | provider payload shape, provider registry, unknown template + missing required-context errors. |
| `tests/test_auth_emails.py` | hermetic | auth template rendering, User-Agent parsing, `format_utc`, client-info/IP extraction, GeoIP no-op behavior. |
| `tests/test_emails_webhook.py` | integration (Postgres) | delivered/opened/clicked/bounced lifecycle, unknown-message ack, `email_stats` + slim list query. |
| `tests/test_password_reset.py` / `tests/test_login_otp.py` | integration (Postgres) | hashed codes, identifier resolution, cooldown, attempt cap, expiry, single-use. |

Auth email sends are patched at the `auth_emails` module boundary
(`mocker.patch.object(auth_emails, "send_...", new=mocker.AsyncMock())`); the
provider itself is patched via `mocker.patch.object(provider,
"get_email_provider")`. Integration tests skip cleanly when Postgres is absent.

---

## 12. Extension recipes

**Add a transactional email**
1. Create `templates/<name>.en.html` (extend `_base.en.html`) + `.en.txt`.
2. `register_template(EmailTemplate(name="<name>", subject="...", html="<name>", text="<name>"))` in `templates.py`.
3. Call `send_template_email(db, "<name>", to=[...], context={...})`.

**Add a provider**
1. Implement `async def send(self, message: OutboundEmail) -> ProviderResult`.
2. `register_provider("<key>", factory)`.
3. Set `EMAIL_PROVIDER=<key>`.

**Add an email-attached file** — register a `Document`, pass its UUID in
`EmailCreate.attachments`; the worker base64-encodes local-disk files. Inline
images use `is_inline=True` + `content_id`.

---

## 13. Known caveats / decisions

- **Reset-code bodies are persisted** in `emails.body_html`/`template_data`.
  This is inherent to keeping an outbound-mail log; the code's 10-minute TTL
  bounds exposure. Redaction of reset bodies is a possible follow-up.
- **`emails` is not CDC'd** — only the compact event/link tables. If you ever
  need body-level warehouse analytics, that is a deliberate, flaggable change.
- **`EMAIL_LOG_ONLY`/`EMAIL_ENABLED`** are safety switches, not a substitute
  for a working provider in production.
- **Attachments from S3** are currently skipped with a loud log (the documents
  module carries all metadata needed to finish this when the S3 client lands).
