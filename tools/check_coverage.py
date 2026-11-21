import argparse
import json
from pathlib import Path


def percentage(value):
    number = float(value)
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError('threshold must be a finite percentage between 0 and 100')
    return number


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description='Check backend line and branch coverage totals.')
    parser.add_argument('--report', type=Path, default=root / 'artifacts' / 'coverage-full-final.json')
    parser.add_argument('--line-threshold', type=percentage, default=90)
    parser.add_argument('--branch-threshold', type=percentage, default=85)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding='utf-8'))
    totals = report['totals']
    line = totals['covered_lines'] / totals['num_statements'] * 100
    branch = totals['covered_branches'] / totals['num_branches'] * 100 if totals['num_branches'] else 100
    print(f'Backend line coverage: {line:.2f}%')
    print(f'Backend branch coverage: {branch:.2f}%')
    if line < args.line_threshold or branch < args.branch_threshold:
        raise SystemExit(
            f'Coverage gate failed: require line >={args.line_threshold:g}% and branch >={args.branch_threshold:g}%'
        )


if __name__ == '__main__':
    main()
