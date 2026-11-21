# Security scan review — main remediation

`pip-audit` on runtime/dev hash locks and `npm audit` are separate from source heuristics. Bandit reports source patterns, not a behavioral proof of an exploit or safety.

## B608 dynamic SQL findings

The remaining reported B608 locations were inspected against current call paths:

- `AttributeService._add/_delete`: table and column names come only from fixed `Colors/ColorName/ColorID` and `Sizes/SizeName/SizeID` wrappers; supplied names/IDs are SQL parameters.
- `ConversationService.update_conversation_settings/update_participant_settings`: keys are validated against explicit field allowlists before building assignments; values and IDs are SQL parameters.
- Customer/main/order pagination queries: conditional WHERE fragments are fixed strings; user filters are bound parameters. Customer/product sort fragments come from closed mappings, never raw input.
- Product deletion: dependent table names come from a fixed tuple, product ID is bound.
- Product catalog/search: sorting uses the declared mapping and stable ID tie-break, with values/counts/offsets bound.

These remain scanner findings because f-string SQL fragments are present. They are not suppressed with `nosec` or excluded globally. No uncontrolled input-to-SQL fragment was found in those reviewed call paths; malformed filters/sorts are covered by unit/contract tests. The 2026-11-20 final scan reported **0 HIGH**, with **20 MEDIUM / 4 LOW** retained for review in `artifacts/bandit-review-final.json`; manual disposition grouped 16 as constrained/parameterized constructions and 8 as informational heuristics. This scoped review found no actionable injection/XML vulnerability, but is not a whole-application security certification. Further structural SQL composition via `psycopg2.sql.Identifier` could reduce scanner noise but is not required to pretend the scan returned zero.

## Other retained heuristics and taint paths

- Fixed OAuth field projections and the customer profile projection are source constants; IDs/providers remain bound parameters.
- The call token regex, GitHub OAuth token endpoint and `client_secret_post` method name are not embedded credentials.
- `xml.etree.ElementTree` is used only to create/serialize the sitemap, not to parse untrusted XML; element text is escaped by the serializer.
- Five GitNexus SQL-taint paths were reviewed (`admin products`, contacts, customers, orders and public product search). Request values remain parameters; only validated closed sort/predicate choices affect SQL structure. The catalog stored function is static PL/pgSQL and uses no dynamic `EXECUTE`.

## Queued publication and room lifecycle hardening

Recovery regressions reproduced selected-recipient ACL outages, orphan delivery rooms between join/leave transitions, and post-commit transport errors that could falsely fail a saved message. Numeric destinations with indeterminate local authorization are now suppressed. Join and leave register the latest generation-bound intent before slow authentication and change content/delivery memberships under one lock; stale rollback cannot undo a newer subscription. Best-effort publication and acknowledgement notices log delivery failures without changing the persisted mutation result.

These are deterministic same-process regression proofs, plus the separately recorded disposable-PostgreSQL/Redis runtime checks. They do not establish zero TOCTOU exposure after the final membership snapshot, queue durability/retry/exactly-once delivery, full distributed logout, or cross-worker call state. A publication error may require the receiver to refresh persisted history; no delivery is fabricated.

## Explicit limitations

- CSP still supports inline scripts/styles and handlers in original main templates; it is not nonce-based enforcement. `unsafe-eval` was removed and browser libraries/fonts are local.
- Upload magic/type/size validation and image re-encoding are not antivirus/malware scanning.
- WebRTC local fake-device tests do not prove external NAT/TURN reliability.
- No real provider email/payment/carrier integrations or production database were contacted.
- Cookie-based cart is not advertised as multi-tab/server-side synchronized state. Background identity/credential reads do not rewrite old cookies; race regression and browser checkout verify that fix.
