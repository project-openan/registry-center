from enum import Enum


class Action(str, Enum):
    APPROVAL = "approval"
    GET_AGENT = "get_agent"
    LIST_AGENTS = "list_agents"
    
    # Agent tags action (for agent.py)
    ADD_TAG = "add_tag"
    
    # Tag entity management actions (for tag.py)
    CREATE_TAG = "create_tag"
    GET_TAG = "get_tag"
    UPDATE_TAG = "update_tag"
    DELETE_TAG = "delete_tag"
    LIST_TAGS = "list_tags"