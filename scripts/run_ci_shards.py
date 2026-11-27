# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Run the backend test suite in whole-file chunks with a merged coverage gate.

A single pytest process over the full suite dies silently mid-run on both the
corporate windows image and the github-hosted ubuntu runner (exit code 1, no
traceback, no FAILED lines) once enough child processes have been spawned.
Whole-file chunks keep every intra-file fixture in one process while keeping
each pytest process below the instability threshold; coverage data is appended
across chunks and gated at 85% at the end (statement coverage, per
.coveragerc).
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHUNK_SIZE = 500


def collect() -> dict:
    """Collect per-file test counts (imports every test module once)."""
    out = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '--co', '-q'],
        cwd=str(REPO), capture_output=True, text=True).stdout
    counts = {}
    for line in out.splitlines():
        line = line.strip()
        if '::' in line and line.startswith('tests/'):
            f = line.split('::')[0].replace('\\', '/')
            counts[f] = counts.get(f, 0) + 1
    return counts


def main() -> int:
    counts = collect()
    ordered = sorted(counts)  # tests/cli/ sorts before tests/test_*.py
    chunks, cur, n = [], [], 0
    for f in ordered:
        c = counts[f]
        if cur and n + c > CHUNK_SIZE:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(f)
        n += c
    if n:
        chunks.append(cur)
    print(f'collected {sum(counts.values())} tests in {len(counts)} files; '
          f'split into {len(chunks)} chunks', flush=True)

    failed_shards = []
    for i, chunk in enumerate(chunks, 1):
        total = sum(counts[f] for f in chunk)
        print(f'=== shard {i}/{len(chunks)}: {total} tests in {len(chunk)} files ===',
              flush=True)
        # 崩溃类退出（无 FAILED 行的静默 exit 1）自动重试一次；真实用例失败
        # 重试后仍是失败，结果不变
        for attempt in (1, 2):
            r = subprocess.run(
                [sys.executable, '-m', 'coverage', 'run', '--append', '-m', 'pytest',
                 *chunk, '-q', '--tb=short'],
                cwd=str(REPO))
            if r.returncode in (0, 5):
                break
            if attempt == 1:
                print(f'shard {i} exited {r.returncode}; retrying once', flush=True)
                failed_shards.append(i)

    gate = subprocess.run(
        [sys.executable, '-m', 'coverage', 'report', '--fail-under=85'],
        cwd=str(REPO))
    subprocess.run([sys.executable, '-m', 'coverage', 'xml'], cwd=str(REPO))

    if failed_shards:
        print(f'shards that kept failing after retry: {failed_shards}', flush=True)
        return 1
    return gate.returncode


if __name__ == '__main__':
    sys.exit(main())
