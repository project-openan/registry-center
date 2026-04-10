# agent_registry/config.py
PERSISTENCE_FILE = "agentcard.json"
MAX_REGISTER_NUM = 40
MAX_REQUEST_BODY_SIZE = 1024 * 1024  # 1MB default limit
MAX_URL_LENGTH = 1024  # 1KB default limit
# 最大文件大小限制：100MB
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
TLS_VERSION = "tls.version"
TLS_CIPHER = "tls.cipher"
CONN_TIMEOUT = "connection.timeout"
CONN_MAX = "connection.max"
FLOW_CTL_REGISTER = "flowcontrol.ratelimit.register"
FLOW_CTL_PARALLEL_REGISTER = "flowcontrol.parallelism.register"
FLOW_CTL_QUERY = "flowcontrol.ratelimit.query"
FLOW_CTL_PARALLEL_QUERY = "flowcontrol.parallelism.query"
FLOW_CTL_PARALLEL_UPDATE = "flowcontrol.parallelism.update"
FLOW_CTL_PARALLEL_GET = "flowcontrol.parallelism.get"
AGENT_NUM_MAX = "agent.num.max"
FORWARDED_ALLOW_IPS = "forwarded_allow_ips"
