import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / 'artifacts' / 'coverage-full-final.json').read_text(encoding='utf-8'))
    totals = report['totals']
    line = totals['covered_lines'] / totals['num_statements'] * 100
    branch = totals['covered_branches'] / totals['num_branches'] * 100 if totals['num_branches'] else 100
    print(f'Backend line coverage: {line:.2f}%')
    print(f'Backend branch coverage: {branch:.2f}%')
    if line < 90 or branch < 85:
        raise SystemExit('Coverage gate failed: require line >=90% and branch >=85%')


if __name__ == '__main__':
    main()
