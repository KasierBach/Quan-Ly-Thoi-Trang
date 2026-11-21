# Main expansion — implementation and verification record

## Scope

This is the approved expansion after the original main remediation, not a claim that every environment is defect-free.

- Worktree: `D:\SQL\dbmstestfileshit\thua-2.0-main` (`main`).
- The original `docs/roadmap-r0` worktree is excluded. Its binary diff SHA-256 remains `6bef9803576ec4e3582ac560c509f760bb5a546b0e4d9f93485a97b3075a26a3`.
- No Supabase/live database, real email/payment, production deployment or OAuth-provider interaction.
- Phase changes remain uncommitted; no new commit or push is part of these local verification results.
- Shared disposable PostgreSQL (`127.0.0.1:55434/thua2_main_test`) runs backend and browser suites **sequentially**, never at the same time.

## Phase 1 — Chat/call/widget

### Completed at local Phase 1 gates (2026-11-20)

- One scoped chat stylesheet replaces the conflicting legacy cascade. Unreferenced chat CSS modules/compiled file are removed; template/JS references were checked before removal.
- Chat is an operational screen: compact site navigation, full-height conversation pane, no marketing footer. Mobile has a real list/back transition, a separate toolbar/composer row, visible send button, safe-area padding and details-sheet close control.
- Native buttons and explicit Vietnamese labels for conversation navigation, actions, reactions, settings and calling. Dialog/menu focus entry, keyboard handling and focus restoration. Light/dark themes use scoped tokens; conversation-color text chooses black/white from measured relative luminance.
- IME Enter guard shared by page/widget/call chat: composition and legacy key-code 229 do not publish; Shift+Enter supports multiline; modifiers/repeats/handled events do not send.
- Exact member-scoped `unread_count`: nondeleted messages by another sender after `last_read_at`; full visible-history policy is preserved. Guest-support entries do not pretend to have participant read cursors.
- Sidebar invalidation emits only `{conversation_id}` to refreshed current participants, including participants who are viewing another room. Actual message content remains selected-room scoped. Client refreshes coalesce and stale responses cannot overwrite newer counts.
- Read badge clears after successful ACK/HTTP persistence, not optimistic client success. HTTP recall/read paths publish only after service success.
- Socket liveness/connection-generation checks stop late identity/room work from restoring disconnected SIDs. Room-manager mutations and bookkeeping are checked atomically; unrelated exceptions remain visible.
- Calls have actual media-state/voice placeholders, stable local/remote participants, connected-only duration, real Fullscreen/PiP feature detection and one remote audio sink that survives local-focused/grid views. No fake quality metric/blinking live badge. Media/timer/listener/focus/scroll teardown is checked.
- Media-status snapshots now include a bounded optional revision. Client rejects older per-type states, so async initial/toggle handlers cannot restore an outdated mic/camera state. Legacy unsequenced events remain compatible until a sequenced state is seen.
- Support widget has theme-aware surfaces, named close/send controls, recovery action and paused polling when the document is hidden. “Kênh hỗ trợ” does not claim a live operator is online.

### Local Phase 1 evidence (2026-11-20)

| Check | Result | Scope/evidence |
| --- | --- | --- |
| Unread PostgreSQL regressions | 14 passed | `tests/integration/test_chat_unread_counts.py` |
| Focused socket/HTTP publication regressions | 192 passed | 48 new cases + existing chat/SDP; final support-admin/call-liveness corrections included |
| Media revision contract | 11 passed | Valid revision forwarding, invalid integer/type bounds, legacy event compatibility |
| JavaScript deterministic suite | 29 passed | 18 chat/client + 11 call UI/ordering lifecycle tests |
| Ruff lint/format | Passed | Formatting of 86 Python files at the current gate |
| Pyright basic | 0 errors/0 warnings | `pyrightconfig.json` |
| ESLint | Passed | `npm run lint` |
| Chat real-browser workflows | 7 passed in latest component run | Private send/upload, guest send, keyboard/theme/multiline, IME event contract, dark persistence, mobile send/back, unselected-room unread update |
| Responsive browser matrix | 1 passed | 1440×900, 1024×768, 768×1024, 390×844, 320×720; viewport-bound composer/actions, no document overflow |
| Full backend/coverage | 1232 passed, no warnings | Line 95.27%, branch 89.22%; `artifacts/phase1-backend-final.log`, `coverage-phase1-final.json` |
| Full browser/WebRTC | 15 passed, no warnings | `artifacts/phase1-e2e-final.log`; includes decoded remote media, toggle state, call chat, grid, screen-sharing and teardown |
| Rendered UI review | Chat: original 2 fixes resolved; call: original 3 fixes resolved (`ship` at each scoped verdict) | General fresh reviewers substituted unavailable shipped Impeccable reviewer; no accessibility/cross-network certification |

The manual Impeccable detector could not resolve Jinja stylesheet links; directly supplied CSS/JS was reviewed, but this scan is incomplete. Remaining reported warnings are the hidden runtime viewer image without a source until an attachment opens, and the existing locally hosted Vietnamese-capable Inter font. Neither is called a detector pass. Taste's generic marketing build gate reported `GATE: OFF` (no marketing build active); Operate-screen acceptance uses the scoped interaction/viewport/screenshot evidence, not a fabricated skill-gate result.

Intermediate failures were fixed rather than skipped: ambiguous accessible selector, CSP-safe predicate function, 1024px storefront-navbar overflow, details overlay close action, and mobile Back autofocus opening an unintended search dropdown. Logs are local artifacts, not proof of final acceptance until the final aggregate runs complete.

### Limits

- WebRTC verification uses Chromium fake media devices and local ICE. It is **not** evidence of real microphones/cameras, TURN deployment, NAT/cross-network connectivity or production group calls.
- Browser IME test dispatches the composition event contract; native OS IME input is not automated by Playwright.
- Functional/visual checks are not full assistive-technology or WCAG certification.
- Large-room unread-query indexing awaits representative `EXPLAIN (ANALYZE, BUFFERS)` evidence; no speculative production migration.
- Group mesh, OAuth, geocoding and multi-worker Redis were not Phase 1 claims; their later scoped evidence and remaining limits are recorded below.

## Phase 2 — Storefront/admin polish and SEO/performance

This section preserves the Phase 2 component checkpoint; the final aggregate below supersedes it.

- Full offline suite: **1291 passed**, 213 deselected at the integrated Phase 2 checkpoint.
- Product metadata, image loading, real 404/recovery and admin dark form/chart E2E: **3 passed**.
- Dedicated HTTP-asset tests: **117 passed**; bounded caching/gzip now works for fixed static content with ordinary guest/account cookies, but not responses containing private/token/session-write data.
- Admin visual reviewer scored the original two desktop dark findings resolved (dark chart surfaces/readable ticks and navbar foreground). This is narrow screenshot acceptance, not all-theme/device/accessibility certification.
- Shared `/admin/products` now inherits the admin layout only for its admin endpoint; the public catalog remains unchanged.
- Four additional real-chat E2E flows passed: reaction/reply/pin/unpin/recall, typing/read receipt, guarded text-file download and call rejection/redial. These found and corrected stale reaction/pin UI state.

- Public metadata/canonicals/JSON-LD derive from configured trusted origin and stored product/variant facts. Crawler routes are isolated from chat/session initialization; private/auth routes remain non-indexable.
- Image space is reserved from existing crops/verified local asset dimensions. Primary images stay eager; below-fold content is lazy. No external/request-time image conversion pipeline.
- Asset caching/compression is limited to approved public static text/crawler responses. HTML carrying CSRF or guest identity, private/download/stream/socket responses are excluded.
- Admin preserves its functional color/status/chart conventions. Shared layout removes the storefront marketing footer and nested viewport scroll; scoped theme surfaces/chart chrome respond to account dark preference.
- Executable script syntax checks now distinguish JSON-LD and parse those blocks as JSON instead of JavaScript.
- New E2E gates: product metadata/image loading, real 404/recovery/noindex, admin dark chart/form surfaces.

## Phase 3 — More real-user browser flows

- Twelve new customer/recovery E2Es passed locally (64.20s): registration/autologin, newsletter/contact validation and saved records, profile/address persistence and checkout defaults, password-change second-context revocation with cart retained, cart removal, exactly-once Pending cancellation/stock restoration, literal review/comment content, autocomplete keyboard recovery, account dark persistence, invalid-phone checkout recovery and suppressed-mail one-use reset.
- Four additional chat flows passed locally (35.98s), including actual reaction/reply/pin/unpin/recall, typing/seen, guarded file download and rejected-call/redial cleanup.
- New page helpers use real form submissions/navigation, not injected state to complete behavior. Fixtures contain only synthetic data, block remote integrations and suppress mail.
- These tests caught a real account initialization defect (`bootstrap` accessed before load) and duplicate address element ID, both fixed. Selector/icon-accessible-name mismatches and HTML-form CRLF normalization were corrected as test issues rather than claimed as production defects.
- The final browser/backend aggregate is recorded below; component passes here remain useful finding history, not provider/all-environment certification.

## Phase 4 — Security, CI and coverage

- CI definitions include hash-locked `pip-audit`, `npm audit`, a Bandit HIGH-severity gate with a retained report, and separate Python/JavaScript CodeQL analysis with minimal permissions. Final local gates found 0 known Python/frontend dependency vulnerabilities and 0 Bandit HIGH findings. The retained Bandit report has 20 MEDIUM/4 LOW heuristics; manual review classified 16 as constrained/parameterized constructions and 8 as informational, with no actionable injection/XML issue in that scoped review. CodeQL workflow is defined but unrun until an authorized commit/push.
- Added focused security regressions for headers/cookies, rate limits, IDOR boundaries and the line/branch coverage CLI. The last aggregate checkpoint before mesh was **1755 passed**, line **94.85%** and branch **87.47%**. This clears the enforced 90/85 gate but does **not** meet the aspirational 96/91 target.
- No live service, production database or deployment was exercised.

## Phase 5 — Google/GitHub OAuth login and explicit account linking

- Authlib-backed provider registry implements Google signed OIDC validation and GitHub verified-email lookup. Login, explicit link, reauthentication and unlink are separate operations; matching email alone never silently links an identity.
- State/PKCE/nonce records are single-use PostgreSQL rows. Identity changes use row locks and bump `auth_version`; password authentication fails closed for OAuth-only accounts with a null password hash.
- Local evidence: **115** offline protocol/service/route tests and **6** disposable-PostgreSQL identity/state integration tests passed at the Phase 5 checkpoint.
- Real Google/GitHub authorization remains **unrun** because no user-owned client ID/secret has been supplied. No credential is invented, embedded or inferred, so this is not a provider-smoke claim.

## Phase 6 — Address map with guarded geocoding

- Order map access reuses the actual owner/admin order guard. Foreign and nonexistent order IDs share the same 404 boundary. Rendering is explicit-click only and labels the marker as an address estimate, not carrier tracking.
- Coordinates are strictly bounded. Positive results use an address-hash cache. Network geocoding is default-off and requires an explicit public-address-only opt-in plus genuine operator contact metadata; private/confidential shipping addresses are not sent to public Nominatim by default.
- Local evidence at the Phase 6 checkpoint: **90** offline mocked service/route tests, **7** browser map checks, and one owner flow against a real persisted synthetic order with a pre-populated cache. **No outbound geocoding request was sent.**

## Phase 7 — Small-group WebRTC mesh

- The group path is separate from one-to-one calling. A process-local registry authorizes every selected socket generation and directed peer pair, reserves users against overlapping calls, caps rooms at four people and bounds queued ICE/signaling state.
- The client captures local media once and owns one `RTCPeerConnection` per authorized edge. SDP answer handling takes priority over local ICE, and outbound ICE ACKs no longer head-of-line block inbound candidates. Per-peer failures, media state, screen-track replacement, chat and teardown remain isolated.
- Four admitted users form six exact pairs with incumbent offerers. A start request containing four invitees (five total participants) is rejected before any reservation or emission. Client-side five-member groups are also rejected before capture.
- Current local evidence (2026-11-20):

  | Check | Result |
  | --- | --- |
  | Domain, Socket.IO adapter and disposable-PostgreSQL mesh tests | **59 passed** |
  | Full deterministic JavaScript suite | **51 passed** (including SDP/ICE ordering and inbound-vs-outbound ICE fairness regressions) |
  | Cleaned three-Chromium acceptance flow | **1 passed in 24.09s** |
  | ESLint and focused Ruff | Passed |

- The browser flow uses three independent authenticated contexts. Each receives two live remote audio/video tracks; mic state and in-call chat propagate; one screen track reaches both peers; the 390×844 layout has no horizontal overflow; one participant can leave while the other two remain connected; final teardown leaves no call, peer or local stream. Debug event/SDP capture was removed before the final pass.
- Screenshot evidence under `artifacts/e2e/mesh/` shows the three-tile desktop/mobile surfaces and the recipient screen-share state. Chromium supplies synthetic green test video. This proves local browser media plumbing only—not real devices, TURN, NAT traversal, cross-network reliability or production calling.

## Phase 8 — Local scale and load evidence

- Runtime topology follows Flask-SocketIO's documented multi-process constraints: two separate Gunicorn `gthread` instances with exactly one worker each, Redis message queue, and sticky Nginx. A multi-worker Gunicorn process is not claimed or supported.
- Numeric message content now publishes through conversation+user+`auth_version` delivery rooms. Sockets join these only while viewing the authorized conversation; each post-commit publish queries PostgreSQL for current recipients. A removed member or old auth version therefore is not a Redis target. Guest support and other event families keep their narrower existing paths.
- Local exact-Compose internal-container proof (2026-11-20): two authenticated synthetic clients were attached to distinct workers without host worker ports. Persisted message ID **4** crossed web1→web2 exactly once, ID **5** crossed web2→web1 exactly once, and after web2 left via the real route, persisted ID **6** reached that remote socket **zero** times. Worker error scans were clean.
- Guarded loopback Locust smoke on the **final exact Compose topology**: **5 users / 30 seconds**, 70 CSV-recorded requests, **0 failures (0.0%)**, **p50 9 ms**, **p95 24 ms**, mean **2.41 RPS**, maximum observed 10-second-window **2.7 RPS**. The workload waits 1–3 seconds and one loopback IP sticks to one worker, so this is neither maximum sustainable capacity nor balanced two-worker throughput.
- Offline scale/config guards: **35 passed**. Publication/ACL/lifecycle set after the scale fix: **194 passed**; PostgreSQL publication-target/unread set: **15 passed**. Full Pyright returned 0 errors/0 warnings; focused Ruff lint/format passed.
- Limits remain explicit: calls/presence/generation registries, broad event fanout, cross-worker logout completeness and process-local cache invalidation are not distributed/certified. The internal proof used Socket.IO polling; proxy WebSocket upgrade and shared limiter semantics were not separately runtime-certified. Temporary scale containers/network were removed after proof.

## Recovery and boundary hardening after the previous checkpoint

The checkpoint below is the superseded pre-recovery record; the final table at the end of this
section is the current source-state evidence. An interrupted aggregate run in between produced
no coverage report and is not a passing run.

- Unbound Flask extensions now live in `app/extensions.py`; package-root imports retain the same singleton objects. Attachment persistence/storage primitives live in `attachment_storage.py`, with the public `AttachmentService` facade preserved and canonical message authorization still in `ChatService.get_message_access`. A fresh GitNexus index reports zero import cycles.
- Identity revalidation now accepts the caller's transaction cursor, so `get_access`, participants and history reads never borrow a second pool slot while holding one. A disposable one-connection PostgreSQL fixture proves authenticated chat reads/mutations complete on a single slot and stale `auth_version` still fails closed with 401.
- New behavioral coverage protects malformed OAuth/identity ownership and transaction failures, bounded HTTP asset reads, geocode cooldown/contact parsing, corrupted recently-viewed session recovery, exact direct-room concurrency and final-member attachment cleanup.
- SEO image URLs now reject ASCII DEL as well as the existing control/whitespace/path guards. The new failing DEL regression passed after the production fix.
- Numeric queued publications omit destinations whose local selected-recipient authorization is indeterminate. Post-commit publication/cleanup/notice errors are logged without turning an already-persisted message into a false failed mutation.
- Content and delivery rooms enter in one locked transition. Both join and leave register their generation-bound intent before slow authentication; older work cannot remove or restore a newer room subscription, and stale rollback cannot undo a newer join.
- Direct-call local ICE is paced behind server acknowledgements and waits for the SDP answer before flushing, with a cancellation regression proving a retired call cannot drain late ACKs. Mesh signaling now revalidates only the exact directed pair per candidate instead of refreshing the whole room, and media/stream status publishes exactly one room snapshot per update; the server-side full-room refresh remains on join/leave/room-state paths.
- Independent fresh-eyes visual review of all seven final mesh screenshots returned **ACCEPT** (layout, Vietnamese labels/diacritics, "(Bạn)" self-labels, share-state buttons, mobile fit all clean). Its two non-blocking notes were closed: the composer hint now keeps "xuống dòng" together on wrap (`&nbsp;` in both `messages.html` and `mesh_call.html`), and the mobile below-fold note is confirmed by `mesh-call.css` (`max-height: calc(100dvh - 32px)` + `overflow: auto`), with the mesh browser flow re-passing after the text change.
- These tests are offline lifecycle/failure evidence except the explicitly labelled disposable-PostgreSQL integration checks. They do not establish Google/GitHub provider, public-geocode, cross-network WebRTC or distributed-revocation completeness.

## Final local aggregate checkpoint (2026-11-20, post-recovery)

| Gate | Final result |
| --- | --- |
| Backend unit/contract/PostgreSQL (`not e2e`) | **1986 passed**, 42 E2E deselected |
| Backend coverage | **96.46% lines / 92.13% branches**; both the enforced 90/85 gate and the aspirational 96/91 target passed |
| Real-browser E2E | **42 passed**, 1986 deselected, including direct and three-member mesh WebRTC flows together |
| Offline CI-equivalent pytest | **1783 passed**, 245 integration/E2E deselected |
| JavaScript | ESLint passed; **53/53 tests passed** (new direct-call ICE pacing and cancellation regressions) |
| Python static gates | Ruff format/lint passed; Pyright **0 errors / 0 warnings** |
| Dependency/security | runtime + dev `pip-audit`: 0 known vulnerabilities; `npm audit`: 0; Bandit HIGH: 0, retained 20 MEDIUM / 4 LOW manually reviewed with no actionable injection/XML finding |
| Docker | final image built non-root (`appuser`), one-worker `gthread`, `pip check` clean offline |
| Exact two-worker Compose | all five services healthy, `/product/1` 200, cross-worker IDs 4/5 exactly once, post-leave ID 6 delivered zero times, worker error scan clean |
| Protected roadmap worktree | binary diff SHA-256 remained `6bef9803576ec4e3582ac560c509f760bb5a546b0e4d9f93485a97b3075a26a3` |

The expansion remains local and uncommitted. A fresh GitNexus check records zero import cycles;
the change set is still large, so green gates are not an all-environment or production
certification. GitHub Actions/CodeQL, real OAuth providers, public geocoding, TURN/NAT/cross-network
media, deployment and live DB migrations were not run and must not be inferred from the local checkpoint.

## Superseded pre-recovery checkpoint (2026-11-20)

Kept for the evidence trajectory; superseded by the post-recovery table above. It recorded
1853 backend passes, line 94.73% / branch 88.56%, 42 E2E passes, 1654 offline passes,
51 JavaScript passes, the same static/dependency/Docker/scale results, and two reported
import cycles that the recovery refactor has since removed.

## Remaining external gates

| Area | Status |
| --- | --- |
| Real Google/GitHub authorization | Blocked until user-owned client credentials are supplied |
| Public network geocoding | Default-off; not approved for private shipping addresses |
| TURN/NAT/cross-network calls | Not configured or proven |
| GitHub CI/CodeQL and deployment | Not run because no commit/push/deploy was authorized |
| Supabase/live migration | Not touched |

Remote push/CI, live-provider credentials, migrations and deployment require their own authorization and evidence; they are not silently inferred from local checks.
