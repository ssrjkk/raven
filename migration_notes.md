# Migration Notes — P0-03 SSRF Protection & Pydantic Validation

## Summary
Added strict Pydantic request models with SSRF URL validation to all `admin_api.py` endpoints. Raw `dict` body parsing replaced with typed models that enforce constraints automatically.

## Changes

### `raven/core/admin_api.py`
- **Added 8 Pydantic models**: `MonitorCreateRequest`, `MonitorUpdateRequest`, `ConfigUpdateRequest`, `SecretRequest`, `AuthLoginRequest`, `AuthRegisterRequest`, `AuthUpdateRoleRequest`, `SSEPushRequest`
- **SSRF validation**: `MonitorCreateRequest` and `MonitorUpdateRequest` reject targets pointing to:
  - `localhost`, `127.0.0.1`, `0.0.0.0`, `[::1]`
  - `169.254.169.254` (AWS metadata)
  - `metadata.google.internal` (GCP metadata)
- **Updated 7 endpoints** to accept typed request bodies instead of `dict`
  - `admin_monitor_create` (POST `/monitors`)
  - `admin_monitor_update` (PUT `/monitors/{monitor_id}`)
  - `admin_set_secret` (POST `/secrets/{key}`)
  - `admin_update_config_key` (POST `/config/key`)
  - `auth_login` (POST `/api/auth/login`)
  - `auth_register` (POST `/api/auth/register`)
  - `auth_update_role` (POST `/api/auth/users/{username}/role`)
  - `sse_push` (POST `/api/stream/push`)

### Validation rules enforced
| Model | Rule |
|-------|------|
| `MonitorCreateRequest` | `name`: non-empty, alphanumeric; `type`: enum; `target`: SSRF-safe; `interval_seconds`: 10–86400 |
| `MonitorUpdateRequest` | same as above, but all fields optional |
| `ConfigUpdateRequest` | `key`: non-empty, alphanumeric+underscore; `value`: non-empty |
| `SecretRequest` | `value`: non-empty |
| `AuthLoginRequest` | `username`, `password`: non-empty |
| `AuthRegisterRequest` | `username`: alphanumeric; `password`: >= 8 chars |
| `AuthUpdateRoleRequest` | `role`: one of `admin`, `user`, `viewer`, `banned` |
| `SSEPushRequest` | all fields optional with sensible defaults |

### `tests/core/test_admin_api_validation.py`
- 34 new tests covering happy paths, SSRF blocks, boundary values, and edge cases

## Risk Assessment
- **Low risk**: Pydantic models define stricter input contracts; FastAPI automatically returns 422 with error details for invalid input instead of server-side errors
- **Breakage only if client sends invalid data** that was previously silently accepted (e.g., empty names, interval < 10s, short passwords). These are security/bug fixes, not regressions.
- **audit_logger sensitive call** in `admin_set_secret` now passes `body.value` directly — no longer unwraps `body.get("value", "")`; `SecretRequest` enforces non-empty, so this is safe.

## Deploy Steps
1. Run `pytest tests/ -x` — expected 650 passed, 6 skipped
2. Run `ruff check raven/ && mypy raven/core/admin_api.py` — no new issues
3. Deploy as minor version bump (v0.4.1)
4. Monitor API error logs for spike in 422 responses (indicates clients sending invalid data)
5. Update API docs / OpenAPI schema (FastAPI auto-generates from Pydantic models)

## Rollback
If issues arise, revert the commit with:
```
git revert <commit-hash>
```
No database migrations needed — all changes are request/response layer only.
