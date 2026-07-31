# Architecture Improvements & Zoho Auth Refactor Plan

## Goal Description
Following the guidelines established in the `master-prompt.md`, this plan outlines improvements to the newly created Hierarchical Settings module to bring it into strict compliance with the project's enterprise doctrines (FBA layering, N+1 explicit strategies, and upsert batching). 

Additionally, it will implement a configurable authentication toggle for the Zoho OAuth flow, allowing `/initiate`, `/callback`, and `/revoke` to optionally bypass JWT authentication.

## Proposed Changes

### 1. Configurable Auth for Zoho OAuth Flow
Currently, the endpoints in `zoho/auth/api.py` hard-require `CurrentUser`. 
- **Change**: Introduce `ZOHO_AUTH_REQUIRE_USER: bool = True` in `app/core/conf.py`.
- **Change**: Create a custom dependency `OptionalZohoAuthUser` in `zoho/auth/api.py` (or `deps.py`) that checks the `ZOHO_AUTH_REQUIRE_USER` flag. If `True`, it runs the standard `get_current_user` dependency. If `False`, it permits the request without a token.

### 2. Strict FBA Layering (System Module)
I combined SQL Alchemy execution logic (crud) and business logic (service) inside `app/modules/system/service.py`. The `master-prompt.md` strictly dictates `api -> schema -> service -> crud -> model`.
- **Change**: Create `app/modules/system/crud.py` to house all SQL statement generation and execution (e.g., `get_setting_definition_by_key`, `upsert_setting_value`).
- **Change**: `app/modules/system/service.py` will purely contain the business logic, type inference (`_infer_type`), hierarchy resolution, and orchestrate calls to `crud.py`.

### 3. N+1 Doctrine & Loader Strategies
The relationships in `app/modules/system/model.py` (`SystemModule.groups`, `SettingGroup.definitions`, etc.) currently rely on implicit lazy loading (which under `AsyncSession` will raise `MissingGreenlet`).
- **Change**: Update `model.py` relationships to explicitly specify the loader firewall: `lazy="raise_on_sql"`. Any cross-table data fetches will be explicitly joined (`selectinload` or `joinedload`) in `crud.py`.

### 4. Postgres Upsert (INSERT ON CONFLICT)
The auto-provisioning logic in `set_setting` performs sequential `SELECT` followed by `INSERT` for Module, Group, Definition, and Value. 
- **Change**: Optimize `crud.py` to use SQLAlchemy's Postgres-specific `INSERT ... ON CONFLICT DO UPDATE` (or `DO NOTHING`) to handle the Upsert semantics cleanly and atomically, reducing the query count per setting-save significantly.

## Open Questions

> [!CAUTION]
> 1. **Optional Auth Fallback:** If `ZOHO_AUTH_REQUIRE_USER` is set to `False` and an unauthenticated user completes the OAuth flow, the `updated_by` field in the `SettingValue` will lack a real user ID. Should we default to a system string like `"system_anonymous"` in this case?
> 2. **Audit Logging in CRUD vs Service:** The `SettingAuditLog` insertion currently happens in the Service. Since an Upsert via `INSERT ON CONFLICT` happens entirely in PostgreSQL (making it harder to extract the `old_value` for the audit log without returning the prior row), I plan to keep the `SELECT -> UPDATE` pattern for the final `SettingValue` specifically so we can accurately record the `old_value`. Are you okay with this slight tradeoff for better audit trails?

## Verification Plan
1. Toggle `ZOHO_AUTH_REQUIRE_USER` to `False` and hit `/api/zoho/auth/initiate` without a Bearer token; it should redirect successfully.
2. Toggle it to `True` and hit it without a token; it should raise a 401 Unauthorized `AuthError`.
3. Check the auto-provisioning of `system` settings to ensure the new `crud.py` Upsert logic correctly initializes missing parent rows without throwing `MissingGreenlet` exceptions due to the new `raise_on_sql` loader strategies.
