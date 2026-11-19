# Security scan review — main remediation

`pip-audit` on runtime/dev hash locks and `npm audit` are separate from source heuristics. Bandit reports source patterns, not a behavioral proof of an exploit or safety.

## B608 dynamic SQL findings

The remaining reported B608 locations were inspected against current call paths:

- `AttributeService._add/_delete`: table and column names come only from fixed `Colors/ColorName/ColorID` and `Sizes/SizeName/SizeID` wrappers; supplied names/IDs are SQL parameters.
- `ConversationService.update_conversation_settings/update_participant_settings`: keys are validated against explicit field allowlists before building assignments; values and IDs are SQL parameters.
- Customer/main/order pagination queries: conditional WHERE fragments are fixed strings; user filters are bound parameters. Customer/product sort fragments come from closed mappings, never raw input.
- Product deletion: dependent table names come from a fixed tuple, product ID is bound.
- Product catalog/search: sorting uses the declared mapping and stable ID tie-break, with values/counts/offsets bound.

These remain scanner findings because f-string SQL fragments are present. They are not suppressed with `nosec` or excluded globally. No uncontrolled input-to-SQL fragment was found in those reviewed call paths; malformed filters/sorts are covered by unit/contract tests. The raw scan is retained in `artifacts/bandit-final.json`. Further structural SQL composition via `psycopg2.sql.Identifier` could reduce scanner noise but is not required to pretend the scan returned zero.

## Explicit limitations

- CSP still supports inline scripts/styles and handlers in original main templates; it is not nonce-based enforcement. `unsafe-eval` was removed and browser libraries/fonts are local.
- Upload magic/type/size validation and image re-encoding are not antivirus/malware scanning.
- WebRTC local fake-device tests do not prove external NAT/TURN reliability.
- No real provider email/payment/carrier integrations or production database were contacted.
- Cookie-based cart is not advertised as multi-tab/server-side synchronized state. Background identity/credential reads do not rewrite old cookies; race regression and browser checkout verify that fix.
