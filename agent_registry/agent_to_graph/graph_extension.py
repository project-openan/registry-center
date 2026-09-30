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

"""
Graph extension parameters.

Defines how an agent card extension maps to knowledge graph nodes and
relationships.
"""

from dataclasses import dataclass


@dataclass
class ExtentionParam:
    key: str
    node_label: str
    relationship_type: str


extension_param_list = [
    ExtentionParam(key="role", node_label="role", relationship_type="has_role"),
    ExtentionParam(key="business", node_label="business", relationship_type="handles_business"),
]
