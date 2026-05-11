# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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
from common.util.config_util import get_conf
from common.util.conf_util import get_persistence_conf

PERSISTENCE_CONF = get_persistence_conf()
PERSISTENCE_MODE = PERSISTENCE_CONF.get("persistence.mode", "file")
PERSISTENCE_FILE = "agentcard.json"
PERSISTENCE_METADATA_FILE = "agentregistry.json"
PERSISTENCE_TAGS_FILE = "agent_tags.json"
USE_VECTORDB = str(get_conf().get("use_vectordb", False)).lower() == 'true'
COLLECTION_NAME = "agent_card_collection"
MAX_REGISTER_NUM = 40
MAX_REQUEST_BODY_SIZE = 1024 * 1024  # 1MB default limit
MAX_URL_LENGTH = 1024  # 1KB default limit
# Maximum file size limit: 100MB
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
TLS_VERSION = "tls.version"
TLS_CIPHER = "tls.cipher"
CONN_TIMEOUT = "connection.timeout"
CONN_MAX = "connection.max"
FLOW_CTL_REGISTER = "flowcontrol.ratelimit.register"
FLOW_CTL_PARALLEL_REGISTER = "flowcontrol.parallelism.register"

FLOW_CTL_QUERY = "flowcontrol.ratelimit.query"
FLOW_CTL_PARALLEL_QUERY = "flowcontrol.parallelism.query"

FLOW_CTL_UPDATE = "flowcontrol.ratelimit.update"
FLOW_CTL_PARALLEL_UPDATE = "flowcontrol.parallelism.update"

FLOW_CTL_GET = "flowcontrol.ratelimit.get"
FLOW_CTL_PARALLEL_GET = "flowcontrol.parallelism.get"

FLOW_CTL_RETRIEVE = "flowcontrol.ratelimit.retrieve"
FLOW_CTL_PARALLEL_RETRIEVE = "flowcontrol.parallelism.retrieve"

FLOW_CTL_DEREGISTER = "flowcontrol.ratelimit.deregister"
FLOW_CTL_PARALLEL_DEREGISTER = "flowcontrol.parallelism.deregister"

FLOW_CTL_JWK = "flowcontrol.ratelimit.jwk"
FLOW_CTL_PARALLEL_JWK = "flowcontrol.parallelism.jwk"

AGENT_NUM_MAX = "agent.num.max"
FORWARDED_ALLOW_IPS = "forwarded_allow_ips"
TAG_MAX_COUNT = "tag.max.count"
TAG_MAX_LENGTH = "tag.max.length"

OWNER_ISOLATION_ENABLED = str(get_conf().get("owner.isolation.enabled", "false")).lower() == 'true'
OWNER_VALIDATION_MODE = get_conf().get("owner.validation.mode", "strict")
