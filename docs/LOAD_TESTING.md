# Phase 8: local load-testing and scale foundations

**Status: scoped local Phase 8 evidence recorded on 2026-11-20. This remains a test foundation, not deployment approval.**
These files do not deploy anything. Never use the original worktree, a production
application/database, Supabase, live users, OAuth/API tokens or an external load target.
Obtain the coordinator's exclusive local DB/runtime slot before starting Docker,
seeding, opening test workers or running any load. Do not overlap integration/E2E runs.

## Topology and what it does not promise

`docker-compose.scale.yml` is a **standalone** local test stack. Do not combine it
with the base compose file and do not change the existing runtime deployment.

- Nginx `ip_hash` -> `web1` and `web2`, each running Gunicorn **`--workers 1`**,
  `gthread`, 16 threads with the existing threading/simple-websocket transport.
- Nginx preserves affinity for polling/WebSocket upgrades, forwards upgrade headers
  and overwrites forwarded client headers; exactly one proxy is trusted by Flask.
- Redis **7.4.2-alpine**, internal only: database 0 for shared Flask-Limiter counters,
  database 1 for Flask-SocketIO `SOCKETIO_MESSAGE_QUEUE`. Redis is disposable, not a
  durable chat store. Existing message persistence remains in PostgreSQL.
- Dedicated ephemeral PostgreSQL **`thua2_main_test`**, internal only and backed by
  tmpfs. It is separate from the serial E2E DB at 55434 and is seeded with
  `docker compose exec`; no database port is exposed to the host. Only Nginx (4011)
  is published on 127.0.0.1. Web/Redis/PostgreSQL have no host ports.
- Web/Redis/Nginx filesystems are read-only with explicit writable scratch paths;
  web instances share one local upload volume. Bootstrap and proxy mounts are `:ro`.
  The internal backplane prevents web/database/Redis external egress. OAuth, geocode
  and external image API credentials are blank/disabled; outbound mail is suppressed.

Flask-SocketIO's documented multi-instance requirements are **sticky load balancing
AND a message queue**. Gunicorn `--workers 2` alone is **not supported** for this
application. Start separate one-worker instances behind the sticky proxy instead.
See [Flask-SocketIO deployment](https://flask-socketio.readthedocs.io/en/latest/deployment.html#using-multiple-workers).
The existing single-process configuration remains unchanged when the queue is absent.

### Explicit remaining limits and acceptance gates

1. **Call/client/presence/generation registries remain process-local.** Redis
   distributes authorized Socket.IO room events, not these domain registries. Numeric
   message content uses a conversation+user+`auth_version` delivery room joined only
   while that socket is viewing the conversation; the publisher derives current targets
   from PostgreSQL. A one-to-one call whose peer SID exists only in the other worker must
   still be rejected with socket status **409**, with no call object/incoming-call emitted.
   Keep all call users on one process until a shared authoritative call store or
   **conversation-aware** affinity exists. `ip_hash` is client-IP affinity, not call affinity.
2. **Only persisted numeric room-message delivery is proven cross-worker in this phase.**
   The 2026-11-20 internal harness connected two authenticated synthetic clients to two
   distinct one-worker containers, joined through the real ACL handler, then observed
   persisted IDs `4` (web1 -> web2) and `5` (web2 -> web1) exactly once. After web2
   left through the real HTTP route, web1 persisted ID `6` and web2 received zero copies.
   Workers were not exposed on host ports; Redis carried the scoped event.
3. **Remote logout and other cross-worker event families are not certified.** Current
   membership and `auth_version` gate the proven message publication targets, but this is
   not proof of distributed typing/reactions/pins/receipts/settings, reconnects, call
   signaling or complete remote session revocation. Do not enable the two-instance stack
   for real users until those gates are resolved.
4. **`app/cache.py` remains a per-app in-process query cache.** Mutations invalidate
   only the receiving process; the other instance can remain stale until its existing
   TTL expires. Shared Redis rate limiting/Socket.IO is **not** shared cache invalidation.
5. All virtual users launched on one loopback host normally share one proxy-visible
   source IP; `ip_hash` therefore sends them to **one instance**, not an evenly loaded
   pair. `X-Scale-Worker` is a local diagnostic response header. Docker NAT may make
   even multiple local clients share an IP. Do not claim two-worker throughput from
   such a run or trust a forged `X-Forwarded-For` to select a worker.
6. Limiter counters are shared, but their correctness across instances still needs
   an actual serial acceptance check. All local virtual users may share one quota:
   HTTP **429 counts as an error**, not a performance success. Do not disable limits,
   mass-login, or interpret a rate-limited result as maximum server capacity.

## Dependency gate

`redis==5.2.1` is a minimal runtime addition; both hash locks retain existing package
versions. `async-timeout==5.0.1` is conditional on Python <3.11.3. Locust was already
in `requirements-dev.in`, locked at **2.47.0**; no new Locust dependency tree or upgrade
is required. Install only after the frozen-lock/runtime slot is released:

```powershell
# From D:\SQL\dbmstestfileshit\thua-2.0-main, never the original worktree.
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
```

This is a local development installation, not a production release. The Docker image
installs only runtime `requirements.txt`, not the development/load tools.

## Offline checks first (no DB, server, Docker or HTTP traffic)

```powershell
.\.venv\Scripts\python.exe tools/load_test.py
.\.venv\Scripts\python.exe -m pytest tests/contract/test_scale_config.py -q
```

The wrapper previews by default and prints **NOT RUN**, not invented metrics. Guard
contracts use stubs; queue-init contracts mock SocketIO initialization and open no
Redis connection. Invalid remote URLs/configuration are rejected before any request.

## Local setup — only after exclusive runtime/DB-slot approval

Choose an off-peak local window. There is no automatic scheduling or seed/reset.
Set `SCALE_SECRET_KEY` to an independently generated value of at least 32 characters
and `SCALE_POSTGRES_PASSWORD` to an independently generated **URL-safe** local-only
password in this shell. **No real secret values belong in files, examples or logs.**
Use the same secret for both workers. Do not reuse production secrets or environment.
Compose deliberately requires both variables and does not load any app `.env` file;
`DISABLE_DOTENV=1` prevents the app from loading one. Clear remote `DATABASE_URL` and
production `APP_ENV`/`FLASK_ENV` from the load-runner shell; do not change global settings.

```powershell
# Syntax check does not start containers. --quiet avoids displaying substituted secrets.
docker compose -f docker-compose.scale.yml config --quiet
# Local image pull/build and runtime startup require the released coordinator slot.
docker compose -f docker-compose.scale.yml up --build -d
# PowerShell: prepend the session-local authorization statement to the fixture,
# then stream both into psql inside the internal database container.
$seed = "SELECT set_config('thua2.allow_test_seed','loopback-disposable',false);`n" + `
    (Get-Content db/seed_test.sql -Raw)
$seed | docker compose -f docker-compose.scale.yml exec -T postgres-test `
    psql -v ON_ERROR_STOP=1 -U postgres -d thua2_main_test
```

The seed is explicit and additive, with reserved fixture checks; the wrapper never
seeds or starts Docker. Re-seed only if the disposable test DB has been recreated.
The reserved products are IDs 1/2. Optional future authenticated tests may use only
`customer@example.test` / **`TestUser123!`** from `db/seed_test.sql`; they are not live
credentials. The supplied workload performs **no login** and needs no auth token.

## Anonymous GET workload and output

The fixed 2:5:3 mix requests `/`, `/products`, and `/product/1`, waits 1–3 seconds,
and expects HTTP 200. No crawling, remote images, checkout/mutations, login/OAuth,
mail/maps or Socket.IO load are performed. Home/product GETs can still create the
existing guest-chat fixture/session state, so the DB must remain disposable.

The guard runs at initialization, test start (including UI host changes), per-user
start and before each request. Only an explicit loopback HTTP(S) origin with a port
is allowed; `localhost` is rewritten to literal 127.0.0.1. Execution requires either
a validated loopback `TEST_DATABASE_URL` for `thua2_main_test`, or
`SCALE_INTERNAL_DATABASE_CONFIRMED=true` set only after the exact isolated Compose DB
has been seeded through `docker compose exec`. A supplied remote `DATABASE_URL`,
production configuration or distributed/cloud runner is refused. Environment proxies
are disabled. Redirects are **never followed**, even to another local URL; every
non-200/redirect/429 is a recorded failure. The flag cannot attest an independently
running server: use only this exact internal stack, never a local proxy/tunnel to production.

```powershell
# After the exact internal database seed succeeds in this shell:
$env:SCALE_INTERNAL_DATABASE_CONFIRMED = 'true'
# Still a preview, no requests.
.\.venv\Scripts\python.exe tools/load_test.py --users 5 --seconds 30
# After local approval plus the internal seed/confirmation above.
.\.venv\Scripts\python.exe tools/load_test.py --execute --yes-local-load --users 5 --seconds 30
# Offline summary of a completed measured run.
.\.venv\Scripts\python.exe tools/load_test.py --summarize artifacts/load/storefront
```

The wrapper caps 1–50 users and 1–300 seconds and spawns at one user/second. Start
with the five-user smoke. Do not enlarge/parallelize it without a new approved local
window. For manual Locust use, supply `--host http://127.0.0.1:4011 --yes-local-load
--web-host 127.0.0.1`; use the wrapper's generated command as the exact reference.
Locust HTML/report/CSV instructions are in its [configuration documentation](https://docs.locust.io/en/stable/configuration.html#csv).

`artifacts/load/storefront_stats.csv`, `_stats_history.csv`, `_failures.csv` and
`_exceptions.csv` provide the evidence. The offline summary reports measured p50,
p95, mean RPS, **maximum observed 10-second-window RPS** and failures/requests. Locust
percentiles are bucketed/rounded; observed max RPS is **not maximum sustainable
capacity**. Preserve run duration/users, cold-vs-warm state, rate-limit errors,
worker distribution and logs when comparing two runs. A failed/missing/unrun CSV
must not be replaced with guessed latency or throughput.

| Acceptance evidence | Current result |
| --- | --- |
| Local load p50 / p95 / observed max RPS / error rate | **9 ms / 24 ms / 2.7 RPS / 0.0%** — final exact Compose run: 5 users, 30 s, 70 recorded requests; mean 2.41 RPS |
| Real queued room-message delivery web1 -> web2 and reverse | **PROVEN** — final exact Compose IDs 4/5 exactly once; post-leave ID 6 delivered 0 times to removed remote member |
| Sticky polling and WebSocket upgrade across two services | Polling affinity used by internal proof; WebSocket upgrade across proxy **not separately proven** |
| Other-worker-only call rejection | Offline contract only; real socket proof pending |
| Shared rate-limit counters | Configuration only; runtime proof pending |
| Distributed call store, broad event fanout, cache invalidation/logout revocation | **Not implemented / not certified** |

The final measured smoke used the exact corrected Compose stack and generated wrapper
command with five users for 30 seconds. The CSV records 70 requests, zero failures,
p50 9 ms, p95 24 ms, mean 2.41 RPS and maximum observed 10-second-window RPS 2.7.
All loopback virtual users shared one source IP and `ip_hash` selected one upstream,
so these numbers are **not** two-worker balanced throughput or maximum capacity.

For the room-message acceptance, the tracked `tools/verify_cross_worker.py` harness
attaches authenticated synthetic clients directly to the exact stack's separate
`web1`/`web2` containers (no host worker ports), joins numeric conversation 2 through
the application handler and sends through the real persistence path. Run it only from
an ephemeral container on `thua2-scale-test_backplane`:

```powershell
docker compose -f docker-compose.scale.yml run --rm --no-deps web1 `
    python tools/verify_cross_worker.py --worker-a http://web1:4000 --worker-b http://web2:4000
```

The final run's IDs 4 and 5 crossed in opposite directions exactly once. Web2 then
left via `/api/conversations/2/leave`; persisted ID 6 produced zero deliveries to that
client. The harness refuses non-internal worker URLs and uses Socket.IO polling; it does
not certify WebSocket upgrades, remote logout, or any other event family.

After a permitted run, stop only this local stack when its runtime slot is released:
`docker compose -f docker-compose.scale.yml stop`. No prune, database reset, volume
delete, global preferences changes, commits or pushes are part of this phase.
