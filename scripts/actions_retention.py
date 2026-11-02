"""Keep the latest workflow runs; never delete active runs or the current run.

This operates on Actions history only, not Releases, Git tags or source commits.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess


def deletion_ids(runs: list[dict], keep: int = 3, current: int = 0) -> list[int]:
    if keep < 1:
        raise ValueError('keep must be positive')
    unique = {int(run['id']): run for run in runs}
    ordered = sorted(unique, reverse=True)
    retained = set(ordered[:keep])
    if current:
        retained.add(current)
    return [run_id for run_id in ordered if run_id not in retained
            and unique[run_id].get('status') == 'completed']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--keep', type=int, default=3)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.repo or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        parser.error('A valid owner/repository is required')
    pages = json.loads(subprocess.check_output([
        'gh', 'api', '--paginate', '--slurp',
        f'repos/{args.repo}/actions/runs?per_page=100'], text=True, encoding='utf-8'))
    runs = [run for page in pages for run in page['workflow_runs']]
    current = int(os.environ.get('GITHUB_RUN_ID', '0'))
    candidates = deletion_ids(runs, args.keep, current)
    print(json.dumps({'repository': args.repo, 'keep': args.keep,
                      'current': current, 'delete_ids': candidates}))
    if args.dry_run:
        return
    for run_id in candidates:
        # Recheck after planning: a user may have rerun an old workflow meanwhile.
        state = json.loads(subprocess.check_output([
            'gh', 'api', f'repos/{args.repo}/actions/runs/{run_id}'], text=True, encoding='utf-8'))
        if state['status'] != 'completed' or run_id == current:
            continue
        subprocess.run(['gh', 'api', '--method', 'DELETE',
                        f'repos/{args.repo}/actions/runs/{run_id}'], check=True)
        print(f'Deleted Actions run {run_id}')


if __name__ == '__main__':
    main()
