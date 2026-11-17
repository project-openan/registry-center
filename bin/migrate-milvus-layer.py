#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Migrate Milvus registration entities to the layer-aware schema."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from agent_registry.config import COLLECTION_NAME  # noqa: E402
from agent_registry.persistence.milvus_layer_migration import (  # noqa: E402
    LayerMigrationRequiredError,
    migrate_collection,
)
from common.vector_db.vector_db_client.config.vector_db_config import (  # noqa: E402
    VectorDBType,
    get_vectordb_config_by_type,
)
from common.vector_db.vector_db_client.milvus_client import MilvusDBClient  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill layer metadata in a Registry Center Milvus collection"
    )
    parser.add_argument(
        "--uri", help="Milvus URI; defaults to the configured Milvus URI"
    )
    parser.add_argument(
        "--collection", default=COLLECTION_NAME,
        help=f"Source collection (default: {COLLECTION_NAME})"
    )
    parser.add_argument(
        "--target-collection",
        help="Replacement collection name when rebuilding a collection"
    )
    parser.add_argument(
        "--mode", choices=("auto", "in-place", "rebuild"), default="auto",
        help="Migration mode; auto updates collections that already declare layer"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="Number of entities read/written per batch (default: 500)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate the collection and print the selected migration mode"
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    configured = get_vectordb_config_by_type(VectorDBType.Milvus)
    uri = args.uri or (configured.uri if configured else None)
    if not uri:
        print("Milvus URI is required; use --uri", file=sys.stderr)
        return 2

    client_wrapper = MilvusDBClient({"uri": uri})
    client = getattr(client_wrapper, "client", None)
    if client is None:
        print("Failed to initialize the Milvus client", file=sys.stderr)
        return 2

    def create_target(collection_name: str) -> None:
        created = client_wrapper.create_collection({"collection_name": collection_name})
        if created is None or not client.has_collection(collection_name):
            raise RuntimeError(f"failed to create target collection: {collection_name}")

    try:
        result = migrate_collection(
            client,
            collection_name=args.collection,
            target_collection=args.target_collection,
            mode=args.mode,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            create_target=create_target,
        )
    except (LayerMigrationRequiredError, ValueError, RuntimeError) as exc:
        print(f"Milvus layer migration failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if result.mode == "rebuild" and not args.dry_run:
        print(
            f"Target collection '{result.target_collection}' is ready; "
            "switch the Registry Center collection after validation."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
