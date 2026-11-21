"""Anonymous, local-fixture GET workload; no login, OAuth, cart, map or Socket.IO load."""

import os
from pathlib import Path
import sys

from locust import HttpUser, between, events, task

# Locust adds this file's directory; add only this worktree, never its parent/original.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.load_test import validate_local_configuration  # noqa: E402


@events.init_command_line_parser.add_listener
def add_local_confirmation(parser, **kwargs):
    parser.add_argument(
        '--yes-local-load',
        action='store_true',
        default=False,
        help='Confirm the isolated loopback test stack and approved serial DB slot',
    )


def validate_run(environment):
    options = environment.parsed_options
    if not options or not getattr(options, 'yes_local_load', False):
        raise SystemExit('Refused before requests: --yes-local-load is required')
    if any(getattr(options, name, False) for name in ('master', 'worker', 'cloud', 'processes')):
        raise SystemExit('Only the local standalone runner is approved; no distributed/cloud load')
    if os.environ.get('LOCUST_CLOUD'):
        raise SystemExit('Cloud load is outside the local-only approval')
    if getattr(options, 'web_host', '127.0.0.1') not in {'127.0.0.1', 'localhost', '::1'}:
        raise SystemExit('The load-test UI must bind only to loopback')
    try:
        environment.host = validate_local_configuration(environment.host)
    except ValueError as error:
        raise SystemExit(f'Refused before requests: {error}') from None
    return environment.host


@events.init.add_listener
@events.test_start.add_listener
def guard_run(environment, **kwargs):
    # Recheck at test_start because the UI can change the host after initialization.
    validate_run(environment)


class StorefrontUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.client.base_url = validate_run(self.environment)
        # A proxy from the host environment must never turn loopback into external traffic.
        self.client.trust_env = False
        self.client.proxies.clear()

    def get_page(self, path, name):
        origin = validate_local_configuration(
            self.client.base_url,
            os.environ,
            require_database=os.environ.get('SCALE_INTERNAL_DATABASE_CONFIRMED') != 'true',
        )
        if path not in {'/', '/products', '/product/1', '/product/2'}:
            raise SystemExit('Only the fixed synthetic storefront GET paths are approved')
        with self.client.get(
            origin + path, name=name, allow_redirects=False, timeout=10, catch_response=True
        ) as response:
            if response.status_code != 200:
                # Includes every redirect and 429; neither is hidden as a success.
                response.failure(f'Expected HTTP 200, got {response.status_code}; redirects are never followed')

    @task(2)
    def home(self):
        self.get_page('/', 'GET home')

    @task(5)
    def products(self):
        self.get_page('/products', 'GET products')

    @task(3)
    def product(self):
        # Product 1 is reserved by db/seed_test.sql; no live-product discovery/crawling.
        self.get_page('/product/1', 'GET product fixture')
