# Logging Guide

Enterprise, config-driven logging for the platform (API **and** Celery workers).
One structured pipeline, controlled by layered YAML — turn logging up, down, or
off per environment and per module **without code changes or redeploys** (config
is hot-swappable via bind mount / restart).

## TL;DR

| I want to… | Do this |
|---|---|
| Change global level for an environment | Edit `config/logging/environments/<env>.yaml` → `level:` |
| Debug ONE module in production | Edit `config/logging/modules/<module>.yaml` → `level: DEBUG` |
| Silence ONE module | That module file → `enabled: false` |
| Turn ALL logging off | `LOG_ENABLED=false` (env), or `logging.yaml` → `enabled: false` |
| Force a level/format right now (ops) | Env vars `LOG_LEVEL` / `LOG_FORMAT` |
| Human-readable logs locally | Automatic in `development` (console format) |

## How it works

```
structlog  →  stdlib logging  →  stdout  →  (Docker) Alloy → Loki → Grafana
```

- **One format everywhere.** JSON in staging/production (Loki-queryable),
  colourised console in development. Configured once; the API factory and the
  Celery `setup_logging` signal both call `configure_logging()`.
- **Context on every line.** `request_id` (and `trace_id` when OTel is on) are
  bound by `RequestContextMiddleware` and appear on every log emitted during a
  request — that's what makes `{service="backend"} | json | request_id="…"`
  work in Grafana.
- **Per-module control via the stdlib logger hierarchy.** A rule on `app.zoho`
  governs `app.zoho.client`, `app.zoho.token`, `app.zoho.ratelimit`, … — the
  idiomatic, zero-overhead Python mechanism.
- **Secrets are redacted** before they leave the process (defence in depth).

## Configuration layers (precedence: low → high)

1. **Code defaults** — `app/core/logging/schema.py` (`LoggingConfig`).
2. **Application base** — `config/logging/logging.yaml` (third-party loggers,
   redaction keys, defaults shared by all environments).
3. **Environment profile** — `config/logging/environments/<ENVIRONMENT>.yaml`.
   `settings.ENVIRONMENT` (development | staging | production) picks the file.
   **This is how prod logs differently from dev.**
4. **Per-module files** — `config/logging/modules/*.yaml`. Each declares the
   namespace it governs via `logger:`.
5. **Environment variables** — `LOG_ENABLED`, `LOG_LEVEL`, `LOG_FORMAT`.
   Applied only when explicitly set; an ops escape hatch that beats the files.

Built-in profiles:

| Environment | level | format | caller info |
|---|---|---|---|
| development | DEBUG | console | yes |
| staging | DEBUG | json | no |
| production | INFO | json | no |

## Config file reference

**`config/logging/logging.yaml`** (application base)
```yaml
enabled: true            # master switch (false = silence everything)
level: INFO              # root level (profiles override)
format: json             # json | console
utc: true
include_caller: false    # add filename:lineno:func (verbose)
redact_keys: [password, token, authorization, ...]
loggers:                 # third-party / framework loggers
  uvicorn.access: { enabled: false }   # our middleware emits the access log
  sqlalchemy.engine: { level: WARNING }
```

**`config/logging/environments/production.yaml`** (profile — partial, deep-merged)
```yaml
level: INFO
format: json
```

**`config/logging/modules/zoho.yaml`** (per-module)
```yaml
logger: app.zoho         # governs app.zoho and ALL children
enabled: true
level: INFO
```

Module files shipped: `zoho` (`app.zoho`), `users` (`app.users`),
`security` (`app.security`), `documents` (`app.documents`),
`tasks` (`app.tasks`). Add a module by dropping a new `*.yaml` with its
`logger:` namespace — no code change.

## Recipes

**Chase a Zoho token bug in production without flooding everything else:**
```yaml
# config/logging/modules/zoho.yaml
logger: app.zoho
level: DEBUG
```
Restart the backend/worker (or remount config). Everything else stays at INFO.
Then in Grafana: `{service=~"backend|celery-worker"} | json | logger=~"app.zoho.*"`.

**Temporarily silence the noisy documents module:**
```yaml
# config/logging/modules/documents.yaml
logger: app.documents
enabled: false
```

**Emergency: turn all app logging off (e.g. a log-spam incident):**
```bash
# set on the backend/worker services and restart
LOG_ENABLED=false
```

**Force DEBUG across the stack for 10 minutes (ops):**
```bash
LOG_LEVEL=DEBUG    # beats every YAML file; unset to revert to profile
```

## Using the logger in code

```python
import structlog
logger = structlog.get_logger("app.zoho.client")   # namespace = module file

logger.info("zoho_api_call", method="GET", path="/items", status=200)
# password=… / authorization=… / token=… are auto-redacted, even nested.
```

Always use a dotted `app.<module>.<area>` name so the per-module config applies.
Log **events** (short snake_case) with structured key/values, never f-strings.

## Where things live

| Path | Purpose |
|---|---|
| `app/core/logging/schema.py` | Typed config models (validates YAML at startup) |
| `app/core/logging/loader.py` | Loads + deep-merges the layers, applies env overrides (cached) |
| `app/core/logging/setup.py` | `configure_logging()` — builds the structlog/stdlib pipeline |
| `app/core/logging/redaction.py` | Recursive secret-masking processor |
| `app/common/log.py` | Backward-compat facade (`configure_logging`, `get_logger`) |
| `config/logging/` | The YAML layers (baked into the image; bind-mountable) |
