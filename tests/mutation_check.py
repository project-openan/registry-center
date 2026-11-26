# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Mutation guard: prove the suite actually intercepts wrong code.

Coverage only shows that a line *ran*; it does not show that a wrong change
would be *caught*. This script applies a small set of deliberate defects to the
product code, runs the tests that are supposed to protect those behaviours, and
requires every defect to turn at least one test red ("mutant killed").

Every mutation is reverted in a finally block, so the working tree is restored
even if the run crashes.

Usage:
    PYTHONPATH=. python tests/mutation_check.py [--verbose]

Exit code 0 = all mutants killed; 1 = at least one survived (weaker tests).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# file, original snippet, mutated snippet, test files that must fail
MUTATIONS = [
    {
        'id': 'MUT-001',
        'why': 'connection quota must reject with 503 at the limit',
        'file': 'agent_registry/middleware.py',
        'old': 'if self.active_connections >= self.max_connections:',
        'new': 'if False:',
        'tests': ['tests/test_middleware.py'],
    },
    {
        'id': 'MUT-002',
        'why': 'connection quota must be released after an exception',
        'file': 'agent_registry/middleware.py',
        'old': '                self.active_connections -= 1',
        'new': '                self.active_connections -= 0',
        'tests': ['tests/test_middleware.py'],
    },
    {
        'id': 'MUT-003',
        'why': 'tag charset validation must reject illegal characters',
        'file': 'agent_registry/internal/utils/tag_validator.py',
        'old': 'if not self.TAG_PATTERN.match(tag):',
        'new': 'if False:',
        'tests': ['tests/test_tag_validator.py'],
    },
    {
        'id': 'MUT-004',
        'why': 'tag count limit must be enforced',
        'file': 'agent_registry/internal/utils/tag_validator.py',
        'old': 'if len(tags) > self.max_count:',
        'new': 'if False:',
        'tests': ['tests/test_tag_validator.py'],
    },
    {
        'id': 'MUT-005',
        'why': 'password minimum length must be enforced',
        'file': 'common/util/password_util.py',
        'old': 'if len(password) < min_length:',
        'new': 'if len(password) < 0:',
        'tests': ['tests/test_password_generator.py', 'tests/test_password_policy.py'],
    },
    {
        'id': 'MUT-006',
        'why': 'file backend must strip status before parsing the AgentCard',
        'file': 'agent_registry/persistence/file_storage.py',
        'old': 'card_data = {key_: value for key_, value in agent_data.items() if key_ != "status"}',
        'new': 'card_data = dict(agent_data)',
        'tests': ['tests/test_file_storage_coverage.py'],
    },
    {
        'id': 'MUT-007',
        'why': 'certificate without public key must be reported explicitly',
        'file': 'agent_registry/init.py',
        'old': 'if public_key is None:\n                return False, "Certificate has no public key"',
        'new': 'if False:\n                return False, "Certificate has no public key"',
        'tests': ['tests/test_init_coverage.py'],
    },
    {
        'id': 'MUT-008',
        'why': 'UDS client must close the socket when connect fails',
        'file': 'agent_registry/cli/uds_client.py',
        'old': '        if connect_error is not None:\n            client_socket.close()\n            return connect_error',
        'new': '        if connect_error is not None:\n            return connect_error',
        'tests': ['tests/test_cli_coverage.py', 'tests/test_coverage_gaps_persist.py'],
    },
    {
        'id': 'MUT-009',
        'why': 'milvus operations must degrade to empty results without a client',
        'file': 'common/vector_db/vector_db_client/milvus_client.py',
        'old': '        if self.client is None:\n            logger.error("Milvus client is unavailable, operation skipped")\n            return False',
        'new': '        if False:\n            logger.error("Milvus client is unavailable, operation skipped")\n            return False',
        'tests': ['tests/test_vector_db_coverage.py'],
    },
    {
        'id': 'MUT-010',
        'why': 'duplicate credential keys must keep the first entry instead of '
               'letting the last one overwrite it (DEFECT-CRED-1)',
        'file': 'agent_registry/integration/credentials.py',
        'old': '            if key in raw:',
        'new': '            if False:',
        'tests': ['tests/test_integration_edges.py'],
    },
]


def purge_bytecode(path):
    """Drop cached bytecode for a module so the mutated source is really used.

    Without this a mutation whose bytecode was already imported can be served
    from ``__pycache__`` (same size, coarse mtime), making the guard report a
    false survivor or leaving poisoned bytecode behind after the restore.
    """

    cache_dir = path.parent / '__pycache__'
    for cached in cache_dir.glob(f'{path.stem}.*.pyc'):
        cached.unlink(missing_ok=True)


def run_tests(tests, verbose=False):
    cmd = [sys.executable, '-m', 'pytest', *tests, '-x', '-q', '--tb=no', '-p', 'no:cacheprovider']
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env)
    if verbose:
        print(proc.stdout[-800:])
    return proc.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    survivors = []
    for mut in MUTATIONS:
        path = REPO_ROOT / mut['file']
        original = path.read_text(encoding='utf-8')
        occurrences = original.count(mut['old'])
        if occurrences != 1:
            print(f"[SKIP] {mut['id']} {mut['file']}: snippet found {occurrences} times (code drifted)")
            survivors.append(mut['id'])
            continue

        print(f"[RUN ] {mut['id']} {mut['file']}: {mut['why']}")
        try:
            path.write_text(original.replace(mut['old'], mut['new'], 1), encoding='utf-8')
            purge_bytecode(path)
            code = run_tests(mut['tests'], args.verbose)
        finally:
            path.write_text(original, encoding='utf-8')
            purge_bytecode(path)

        if code == 0:
            print(f"[LIVE] {mut['id']} survived -> tests did not catch: {mut['why']}")
            survivors.append(mut['id'])
        else:
            print(f"[KILL] {mut['id']} caught by {', '.join(mut['tests'])}")

    print()
    if survivors:
        print(f"FAILED: {len(survivors)} mutant(s) survived: {', '.join(survivors)}")
        return 1
    print(f"PASSED: all {len(MUTATIONS)} mutants killed")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
