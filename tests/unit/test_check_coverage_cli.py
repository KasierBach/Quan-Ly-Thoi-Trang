"""Coverage CLI contracts use synthetic reports, not a claimed backend coverage run."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import check_coverage


SCRIPT = Path(check_coverage.__file__).resolve()


def report_file(tmp_path, lines=90, branches=85, branch_count=100):
    path = tmp_path / 'coverage.json'
    path.write_text(
        json.dumps(
            {
                'totals': {
                    'covered_lines': lines,
                    'num_statements': 100,
                    'covered_branches': branches,
                    'num_branches': branch_count,
                }
            }
        ),
        encoding='utf-8',
    )
    return path


def run_cli(tmp_path, *args):
    return subprocess.run(
        [sys.executable, '-I', str(SCRIPT), *map(str, args)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize('lines,branches,code', [(90, 85, 0), (89, 85, 1), (90, 84, 1)])
def test_cli_report_from_other_directory_keeps_default_thresholds(tmp_path, lines, branches, code):
    result = run_cli(tmp_path, '--report', report_file(tmp_path, lines, branches))
    assert result.returncode == code
    assert f'Backend line coverage: {lines:.2f}%' in result.stdout
    assert f'Backend branch coverage: {branches:.2f}%' in result.stdout
    if code:
        assert 'require line >=90% and branch >=85%' in result.stderr


@pytest.mark.parametrize('lines,branches,code', [(80, 75, 0), (79, 75, 1), (80, 74, 1)])
def test_cli_accepts_explicit_thresholds(tmp_path, lines, branches, code):
    result = run_cli(
        tmp_path,
        '--report',
        report_file(tmp_path, lines, branches),
        '--line-threshold',
        '80',
        '--branch-threshold',
        '75',
    )
    assert result.returncode == code
    if code:
        assert 'require line >=80% and branch >=75%' in result.stderr


def test_main_without_arguments_uses_original_default_report(tmp_path, monkeypatch, capsys):
    report = report_file(tmp_path)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    report.rename(artifacts / 'coverage-full-final.json')
    monkeypatch.setattr(check_coverage, '__file__', str(tmp_path / 'tools' / 'check_coverage.py'))
    check_coverage.main([])
    assert 'Backend line coverage: 90.00%' in capsys.readouterr().out


def test_cli_preserves_no_branches_convention(tmp_path):
    result = run_cli(tmp_path, '--report', report_file(tmp_path, branches=0, branch_count=0))
    assert result.returncode == 0
    assert 'Backend branch coverage: 100.00%' in result.stdout


@pytest.mark.parametrize(
    'flag,value',
    [
        ('--line-threshold', '-1'),
        ('--branch-threshold', '100.1'),
        ('--line-threshold', 'nan'),
        ('--branch-threshold', 'inf'),
    ],
)
def test_cli_invalid_threshold_is_usage_error(tmp_path, flag, value):
    result = run_cli(tmp_path, '--report', report_file(tmp_path), flag, value)
    assert result.returncode == 2
    assert 'threshold must be a finite percentage' in result.stderr


def test_cli_missing_report_cannot_pass(tmp_path):
    result = run_cli(tmp_path, '--report', tmp_path / 'missing.json')
    assert result.returncode != 0
    assert 'Backend line coverage' not in result.stdout
