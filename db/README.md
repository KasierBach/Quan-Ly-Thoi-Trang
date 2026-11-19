# Reproducible main PostgreSQL schema

`bootstrap.sql` targets PostgreSQL 14+ and initializes an empty database. Replay is additive: missing columns/constraints/indexes are added, views/functions/triggers are replaced without dropping objects, and existing rows are not updated or erased. Newly added legacy checks use `NOT VALID` so old rows are retained while future writes are checked. Existing duplicate case-insensitive emails/reset tokens or incompatible function return types cause a transactional failure, not silent deletion. This is not an instruction to migrate a live database.

## Provenance

Reconstruction uses only the **ignored January 2026 files**, read from the original folder, and SQL contracts in the approved main worktree at `aa0f131e60d4489eea1b16b753d220cd87d34ce3` (2026-04-17). Neither ignored file has Git history for its path; filesystem timestamps are not commit provenance.

| Input | Lines | Filesystem modified (+07:00) | SHA-256 (raw file bytes) |
| --- | ---: | --- | --- |
| `.data/postgresql_schema.sql` | 749 | 2026-01-29 20:56:48 | `53030e9d4b32a8ff714bdb23f8e82024f236722329845f8bdbf86db0fb98b6ba` |
| `.data/chat_migration.sql` | 141 | 2026-01-29 15:20:22 | `8117c36ca71c2c4c066fe9aa55df0418296d2d66c56f8271cf9cfb6ce2570f8d` |

No newer tracked schema/migration, original customer data, `.env`, Supabase, or production connection was used. The unsafe old `DROP ... CASCADE` preamble and duplicate-producing chat backfill are intentionally omitted.

## Contracts and repairs

- Preserve all 12 old `sp_*` SQL functions and seven `vw_*` views, with their existing argument/result names and types. `OrderDetails.Price` is canonical; application detail queries expose both `Price` and `UnitPrice`.
- Add auth `Gender`, `DateOfBirth`, `auth_version` (default 1), and one canonical `Customers.avatar_url` shared with chat; auth exposes `AvatarUrl` as an output alias. Reset `Token VARCHAR(100)` stores a unique lowercase 64-hex SHA-256 digest. Customer/newsletter email uniqueness is case-insensitive.
- Restore advanced chat tables/fields, plus main's `theme_color`, `default_emoji`, and private attachment `storage_name`. Legacy session messages are retained without inventing/migrating conversations. Customer deletion cannot erase retained order/feedback/chat history.
- Add checkout recipient name/phone/email and notes. Atomic conditional inventory updates check positive detail quantities, reserve stock once, adjust edit deltas, and roll back with the caller transaction. Lock orders before variants; callers creating multi-variant carts should sort variants to avoid lock inversion.
- Lifecycle: `Pending -> Processing/Cancelled`, `Processing -> Shipped/Cancelled`, `Shipped -> Delivered`. Same-status function calls are no-ops; `Delivered`/`Cancelled` are immutable. Cancellation groups duplicate variant lines and returns stock exactly once. Pending deletion restocks at the parent; its cascading detail deletes do not return stock again. All revenue views/date-range functions count **Delivered only**, with inclusive end-date coverage.

## Disposable local test seed

Use only the separately launched test Compose project/database. The runner rejects remote hosts, another DB name, and libpq query/fragment overrides **before connecting**; it never reads `.env`, resets rows, or touches Docker containers. Explicit acknowledgement is required.

```bash
export TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55434/thua2_main_test'
python tools/seed_test.py --yes-test-seed
python -m pytest -m integration tests/integration/test_schema.py tests/integration/test_order_database.py
```

The SQL additionally requires the validated connection's `thua2.allow_test_seed=loopback-disposable` setting. `seed_test.sql` is additive/idempotent, refuses collisions in reserved fixture IDs, and only includes synthetic `example.test` accounts, data/dates, and local static images. Accounts are `customer@example.test` (1), `admin@example.test` (2), `other@example.test` (3), all password **`TestUser123!`**. Products/variants 1 and 2 and Delivered/Pending/Cancelled orders are deterministic. Replays do not replenish inventory. Integration fixture resets are separately guarded and belong to the test harness; do not run overlapping suites against the same test database.
