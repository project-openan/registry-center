# agent_registry/config.py
PERSISTENCE_FILE = "./data/agent_registry_data.json"
MAX_REGISTER_NUM = 40
MAX_REQUEST_BODY_SIZE = 1024 * 1024  # 1MB default limit
MAX_URL_LENGTH = 1024  # 1KB default limit
MAX_REQUEST_RATE = "10/minute"  # default 10 requests per minute
