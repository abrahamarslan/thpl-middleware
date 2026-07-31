# Hierarchical System Settings Implementation Plan

## Goal Description
Evolve the simple `SystemSetting` key-value store into a fully relational, enterprise-grade **Hierarchical Configuration Module** based on the provided SQLAlchemy schema. This allows settings to be grouped logically (Module -> Group -> Definition), scoped contextually (Global, Tenant, User), strictly typed, and audited for changes. 

We will also update the Zoho OAuth flow to utilize this new hierarchical structure.

## Architecture Decisions

1. **SQLAlchemy 2.0 Conversion**: 
   The provided SQLAlchemy 1.x style declarative models (e.g., `Column(String)`) will be converted into the modern SQLAlchemy 2.0 style used in `th-middleware` (e.g., `Mapped[str] = mapped_column()`). The standard mixins (`IntPKMixin`, `TimestampMixin`) will be applied to all models.

2. **Auto-Provisioning vs. Explicit Seeding**:
   To ensure a seamless developer experience, the `system.service.set_setting(key, value)` function will **auto-provision** the parent `SystemModule`, `SettingGroup`, and `SettingDefinition` if they don't exist. It will infer them from a dot-notated key (e.g., `zoho.auth.refresh_token` creates module `zoho`, group `auth`, definition `refresh_token` with a default type of `STRING`). 

3. **Audit Logs (Application Layer)**: 
   Setting changes will automatically trigger an insert into the `SettingAuditLog` table via the Python service layer (inside `set_setting`). This allows easy capture of application context (e.g., `changed_by` user ID) without complex PostgreSQL trigger functions.

4. **Context IDs (Loose Coupling)**:
   For `SettingContext.TENANT` and `USER`, the `context_id` will remain a `String(100)` rather than a strict Foreign Key. This allows the settings module to be completely decoupled from the specific `users` or `tenants` tables, making it a truly independent microservice/module.

## Proposed Changes

### 1. `app/modules/system`

#### `app/modules/system/model.py`
Replace the simple KV model with the robust hierarchical models:
- **Enums**: `SettingType`, `SettingContext`.
- **Models**: `SystemModule`, `SettingGroup`, `SettingDefinition`, `SettingValue`, `SettingAuditLog`.
- Mix in `IntPKMixin` and `TimestampMixin`.

#### `app/modules/system/schema.py`
Pydantic schemas corresponding to the new models:
- `SettingValueCreate` / `SettingValueOut`
- `SettingDefinitionOut`

#### `app/modules/system/service.py` (Replaces `crud.py`)
Implement the core setting resolver logic:
- `get_setting(key: str, context: SettingContext = SettingContext.GLOBAL, context_id: str | None = None)`: Resolves a setting. First checks User context (if provided), then Tenant context (if provided), then falls back to Global context, then default value.
- `set_setting(key: str, value: Any, updated_by: str, context: SettingContext = SettingContext.GLOBAL, context_id: str | None = None)`: Auto-provisions the module/group/definition if missing, updates the value, and writes to `SettingAuditLog`.
- `delete_setting(key: str, context: SettingContext = SettingContext.GLOBAL, context_id: str | None = None)`: Removes a specific contextual override.

### 2. Zoho Core Integration

#### `app/modules/zoho/core/token_manager.py`
- Refactor the persistence fallback to use the new `system.service.get_setting("zoho.oauth.refresh_token", SettingContext.GLOBAL)` and `set_setting(...)`.
- We will store the token as a JSON string or STRING depending on the auto-provisioned type.

### 3. Documentation

#### `docs/zoho-oauth-implementation.md`
- Update the existing documentation to reflect the new hierarchical setting structure, referencing `SettingValue` rather than `SystemSetting`.

## Verification Plan

### Automated Tests
- Write a unit test ensuring that `set_setting("module.group.key", "val")` creates the 3 parent records automatically.
- Write a unit test ensuring `get_setting` correctly resolves a `USER` override before a `GLOBAL` default.

### Manual Verification
- Re-run the Zoho OAuth `/initiate` and `/callback` flow.
- Query the database to ensure `zoho` (module), `oauth` (group), `refresh_token` (definition), and the `SettingValue` row are correctly populated, alongside a `SettingAuditLog` entry.
