# Main remediation — 2026-11-17

## Scope and isolation

- Baseline: `main` at `aa0f131e60d4489eea1b16b753d220cd87d34ce3`.
- Corrections live uncommitted in the separate main worktree `D:\SQL\dbmstestfileshit\thua-2.0-main`.
- Original `docs/roadmap-r0` worktree and its pending changes remain unchanged: binary diff SHA-256 before and after `6bef9803576ec4e3582ac560c509f760bb5a546b0e4d9f93485a97b3075a26a3`.
- No commit, merge, push, production DB access, real email/payment or deployment.
- Original main layout/style kept; no editorial redesign/roadmap merge. Broken/mock controls and data statements were corrected or removed.

## Confirmed defects corrected

### Runtime/auth

- Removed fallback secret/bundled image-search key, import-time parent `.env` discovery, unconditional trusted proxy and JSONEncoder monkey patch.
- Test/app configuration can be isolated. Production constraints require explicit secret/hosts/HTTPS URL/shared rate-limit storage and secure cookies.
- Per-app DB pool, transaction cleanup, bounded health retries/capacity wait; no unbounded fallback connections. Per-app bounded cache and mutation invalidation.
- Password/reset validation, hashing, hashed one-use expiring reset token, `auth_version` revocation and DB role refresh. Logout is CSRF-protected POST and revokes existing sockets.
- Avatar content decode/re-encode, bounds, storage field consistency and honest error results.

### Catalog/cart/orders

- Positive integer/money validation, coherent size/color/stock filtering, stable pagination/sorting, canonical prices and Decimal totals.
- Accumulated cart stock checks, authoritative row-price/subtotal readback, buy-now mode through POST/errors, separate temporary vs normal cart, persisted recipient/notes.
- Canonical `Price`/`UnitPrice`/`Subtotal` order detail fields, owner guards and consistent order lifecycle.
- Atomic SQL stock reservation/rollback, exactly-once grouped cancellation, terminal order immutability, no double stock restoration on cascading delete.
- Fixed cross-request cookie race: background identity and credential reads no longer rewrite stale cart cookie; permanent cookies do not refresh per AJAX request. Full-page chat identity/recent-view state is initialized before background requests.
- Removed mock coupons/payment providers/carrier/truck map; COD and stored order status are labelled accurately.

### Admin/reports/contact

- Correct parameter order/data fields, zero stock support, entity/reference deletion guards and shared admin authorization.
- Delivered-only realized-order value, inclusive calendar date ranges, consistent CSV/report filters, exact monetary display, BOM and CSV formula protection.
- Contact reply recipient comes from stored record; disabled/suppressed integrations do not claim delivery.
- Fixed product modal/form/config and unsafe comments/contact modal rendering; no fake scheduling/native XLSX/PDF export claim.

### Chat/browser

- Signed cookie-bound server-issued guest identity; no caller UUID privilege or `OR user_id` history leaks.
- Conversation/message/room ACLs enforced in HTTP/services/events; private chats not broadcast to all admins; sender and recipient auth/version/role rechecked.
- Private uploads with generated storage names, type/content/size checks, atomic records and failed-upload cleanup, guarded downloads and preserved sandbox/no-referrer headers. Filename collision never deletes an existing file.
- Legacy `/static/uploads/chat/*` blocked by app. Existing tracked legacy blob remains on disk; deployment static proxy must not serve that directory directly.
- Credential-gated ChatApp, safe DOM rendering, matching API/event handling, ACK-aware mutations and room join, stale response/call/ICE guards, page/disconnect cleanup.
- Single-peer call ID bound to two connections, autonomous ringing timeout, camera/mic/media teardown and screen-share start/stop. SDP wire CRLF preserved; browser timer binding fixed.
- Python/JS lint defects and duplicate methods resolved; browser libraries/Vietnamese-capable Inter font local and pinned.
- Fixed hidden stock warning overridden by Bootstrap display utility and continuously scaling support button/menu CSS mismatch.

## Final gates (same final source)

| Gate | Actual outcome | Evidence |
| --- | --- | --- |
| Python lint | PASS | `python -m ruff check app run.py tests tools` |
| Python format | PASS, 79 files formatted | `python -m ruff format --check app run.py tests tools` |
| Pyright basic | PASS: 0 errors/0 warnings | `pyrightconfig.json` (not type-check disabled) |
| JavaScript lint | PASS | `npm run lint` |
| JS deterministic tests | 12 passed, no skips | `tests/js/chat-client.test.mjs` |
| Unit + contract + PostgreSQL integration | **1123 passed**, 9 E2E deselected | `artifacts/tests-full-final.txt`, `tests-full-final.xml` |
| Backend statement/line coverage | **95.12%** | `artifacts/coverage-full-final.json` |
| Backend branch coverage | **88.94%** | `artifacts/coverage-full-final.json` |
| Coverage gate | PASS (line ≥90, branch ≥85) | `python tools/check_coverage.py` |
| Browser E2E | **9 passed**, 1123 backend tests deselected, no warnings | `artifacts/e2e-final.txt`, `e2e-final.xml` |
| Runtime and dev dependencies | No known vulnerabilities found | `pip-audit` hash-locked runtime/dev requirements |
| Frontend dependency audit | 0 vulnerabilities | `npm audit --audit-level=low` |
| Docker build/smoke | PASS: non-root `appuser`, healthy; live/ready/login/products/product detail 200 | `artifacts/docker-build-final.txt`, `docker-smoke-final.json`, `docker-smoke-final.log` |
| Diff whitespace + original-worktree preservation | PASS | `git diff --check`, original diff hash unchanged |

Coverage terminal aggregate includes branch points and reads 93.94%; line and branch values above are calculated separately, not confused with aggregate coverage.

## Browser evidence/scope

E2E uses real app, PostgreSQL fixture, actual forms/CSRF and two browser contexts. Setup uses synthetic accounts/dates/products, blocks outbound HTTPS integrations, and configures fake media devices plus local ICE before app startup. No state injection completes the behavior under test.

1. Customer login → variant → quantity update → checkout → persisted confirmation (including real DB totals/recipient).
2. Buy-now order with normal cart preserved.
3. Persisted wishlist add/remove.
4. Admin order transition and actual CSV download.
5. Mobile catalog/menu and no document horizontal overflow (390px).
6. Private two-context chat and guarded image upload; script-looking content stays text.
7. Guest support widget send with server ACK.
8. Voice one-to-one, live remote audio tracks and teardown.
9. Video one-to-one, decoded remote frames, screen-share start/stop and teardown.

Screenshots are under `artifacts/e2e/`, including customer/order/admin/mobile/private-chat and WebRTC/screenshare evidence. Visual smoke is not a complete accessibility/design acceptance audit.

## Test orchestration notes

Earlier failing rounds were kept/repaired, not turned into skips. One concurrently started DB/E2E round was invalidated and is not acceptance evidence (`artifacts/invalidated-concurrent-run.md`). Final backend and E2E runs are strictly sequential.

Werkzeug dev-server aborted file responses initially produced ResourceWarnings. The E2E-only streamed-response wrapper ensures close on abort without buffering/rewriting application content or hiding warnings; final E2E has no warnings. Production Gunicorn smoke runs separately.

## Remaining external/manual limitations (not fake passes)

- No live Supabase migration, production deployment, real SMTP/payment/carrier or real-user/revenue evidence.
- WebRTC verified with Chromium fake devices on local ICE, not real NAT/TURN/inter-network calls. Upload checks are not antivirus.
- CSP still needs inline scripts/styles for original main; not nonce-based. Cookie cart is not a multi-tab server-side synchronized cart.
- Bandit B608 allowlisted SQL-fragment findings remain visible and reviewed in `docs/SECURITY_REVIEW.md`; no blanket `nosec`/exclude and no claim raw scan is zero.
- Render/Vercel templates were corrected but not deployed; Vercel serverless long-lived Socket.IO compatibility not certified.
- Legacy tracked `.pyc` and chat blob are not executed or considered schema/test truth. Public chat blob path is blocked in app; do not expose it through a static reverse proxy.

No known confirmed regression remains in the exercised audit scope at these final gates. This is not a guarantee that every possible environment or future input is defect-free.
