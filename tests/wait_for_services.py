# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Block until the CI database services accept connections.

GitHub Actions only guarantees a *started* container; the engine may still be
initialising. The storage tests self-skip when a backend is unreachable, so a
too-early start would silently downgrade the run to "everything skipped".
This helper turns that into a hard failure instead.

Usage: python tests/wait_for_services.py
Honours the same PG_TEST_* / MYSQL_TEST_* variables the test suite uses.
"""

import os
import sys
import time


def _pg_connect():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get('PG_TEST_HOST', '127.0.0.1'),
        port=int(os.environ.get('PG_TEST_PORT', '5432')),
        user=os.environ.get('PG_TEST_USER', 'opena2a_t'),
        password=os.environ.get('PG_TEST_PASSWORD', 'openA2A_T'),
        dbname=os.environ.get('PG_TEST_DB', 'registry_center'),
        connect_timeout=3,
    )


def _mysql_connect():
    import pymysql
    return pymysql.connect(
        host=os.environ.get('MYSQL_TEST_HOST', '127.0.0.1'),
        port=int(os.environ.get('MYSQL_TEST_PORT', '3306')),
        user=os.environ.get('MYSQL_TEST_USER', 'root'),
        password=os.environ.get('MYSQL_TEST_PASSWORD', 'root'),
        connect_timeout=3,
    )


def wait_for(label, connect, attempts=60, delay=2):
    last = None
    for _ in range(attempts):
        try:
            connect().close()
            print(f'{label} ready')
            return True
        except Exception as exc:  # noqa: BLE001 - probing external service
            last = exc
            time.sleep(delay)
    print(f'{label} never became ready: {last}', file=sys.stderr)
    return False


def main():
    ok = wait_for('postgres', _pg_connect)
    ok = wait_for('mysql', _mysql_connect) and ok
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
