"""Local-only Locust command preview and CSV summary; never imports the Flask app."""

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}
DATABASE_NAME = 'thua2_main_test'


def loopback_target(value):
    """Use literal loopback transport, including when the operator writes localhost."""
    if not isinstance(value, str) or any(ord(char) < 33 for char in value) or '\\' in value:
        raise ValueError('Load target must be an explicit loopback HTTP origin')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (
            parsed.scheme not in {'http', 'https'}
            or parsed.hostname not in LOOPBACK_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or not port
            or parsed.path not in {'', '/'}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
    except ValueError:
        raise ValueError('Load target must be http(s)://127.0.0.1:PORT or http(s)://[::1]:PORT') from None
    host = '[::1]' if parsed.hostname == '::1' else '127.0.0.1'
    return urlunsplit((parsed.scheme, f'{host}:{port}', '', '', ''))


def validate_test_database(value):
    """No connection is opened; reject remote databases and libpq query overrides."""
    try:
        parsed = urlsplit(value or '')
        if (
            parsed.scheme != 'postgresql'
            or parsed.hostname not in LOOPBACK_HOSTS
            or parsed.path != '/' + DATABASE_NAME
            or parsed.query
            or parsed.fragment
            or not parsed.username
            or parsed.password is None
            or not (0 < (parsed.port or 5432) <= 65535)
            or any(ord(char) < 33 for char in value)
            or '\\' in value
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(
            'Load tests require a loopback TEST_DATABASE_URL for thua2_main_test, without overrides'
        ) from None


def validate_local_configuration(host, environment=None, *, require_database=True):
    environment = os.environ if environment is None else environment
    target = loopback_target(host)
    if any(environment.get(key) == 'production' for key in ('APP_ENV', 'FLASK_ENV')):
        raise ValueError('Load tests refuse production configuration')
    for key in ('TEST_DATABASE_URL', 'DATABASE_URL'):
        if environment.get(key):
            validate_test_database(environment[key])
    if require_database and environment.get('SCALE_INTERNAL_DATABASE_CONFIRMED') != 'true':
        if not environment.get('TEST_DATABASE_URL'):
            raise ValueError(
                'Set SCALE_INTERNAL_DATABASE_CONFIRMED=true for the isolated internal Compose DB, '
                'or provide a loopback TEST_DATABASE_URL'
            )
    return target


def summarize_csv(prefix):
    """Read measured Locust outputs, not estimates. RPS is the sampled sliding window."""
    prefix = Path(prefix)
    with Path(str(prefix) + '_stats.csv').open(encoding='utf-8', newline='') as stream:
        aggregate = next((row for row in csv.DictReader(stream) if row.get('Name') == 'Aggregated'), None)
    if aggregate is None or int(aggregate['Request Count']) <= 0:
        raise ValueError('CSV has no measured aggregate requests; no performance result can be reported')
    with Path(str(prefix) + '_stats_history.csv').open(encoding='utf-8', newline='') as stream:
        rates = [float(row['Requests/s']) for row in csv.DictReader(stream) if row.get('Name') == 'Aggregated']
    if not rates:
        raise ValueError('CSV has no measured aggregate RPS history')
    count, failures = int(aggregate['Request Count']), int(aggregate['Failure Count'])
    return {
        'source': str(prefix),
        'requests': count,
        'failures': failures,
        'error_rate_percent': round(100 * failures / count, 3),
        'p50_ms': float(aggregate['50%']),
        'p95_ms': float(aggregate['95%']),
        'max_observed_rps_10s_window': max(rates),
        'mean_rps': float(aggregate['Requests/s']),
        'note': 'Locust rounded percentiles; max observed RPS is not maximum sustainable capacity.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Preview a guarded local load run, or summarize measured Locust CSV')
    parser.add_argument('--host', default='http://127.0.0.1:4011')
    parser.add_argument('--users', type=int, default=5)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--csv', default=str(ROOT / 'artifacts' / 'load' / 'storefront'))
    parser.add_argument('--execute', action='store_true', help='Run Locust only after explicit local DB-slot approval')
    parser.add_argument(
        '--yes-local-load', action='store_true', help='Confirm the isolated local test stack and DB slot'
    )
    parser.add_argument('--summarize', metavar='CSV_PREFIX', help='Read an existing completed run; sends no requests')
    args = parser.parse_args(argv)
    try:
        if args.summarize:
            print(json.dumps(summarize_csv(args.summarize), indent=2))
            return 0
        target = validate_local_configuration(args.host, require_database=args.execute)
        if not 1 <= args.users <= 50 or not 1 <= args.seconds <= 300:
            raise ValueError('Safety limits: 1..50 users and 1..300 seconds')
        if args.execute and not args.yes_local_load:
            raise ValueError('--execute requires --yes-local-load and prior coordinator DB-slot approval')
        command = [
            sys.executable,
            '-m',
            'locust',
            '-f',
            str(ROOT / 'tests' / 'load' / 'locustfile.py'),
            '--host',
            target,
            '--headless',
            '--users',
            str(args.users),
            '--spawn-rate',
            '1',
            '--run-time',
            f'{args.seconds}s',
            '--csv',
            args.csv,
            '--csv-full-history',
            '--web-host',
            '127.0.0.1',
            '--yes-local-load',
            '--exit-code-on-error',
            '1',
        ]
        if not args.execute:
            print(json.dumps({'executed': False, 'command': command, 'metrics': 'NOT RUN'}, indent=2))
            return 0
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        print(json.dumps(summarize_csv(args.csv), indent=2))
        return result.returncode
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    raise SystemExit(main())
