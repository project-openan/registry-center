from enum import Enum


class Action(str, Enum):
    APPROVAL = "approval"
    GET_AGENT = "get_agent"
    LIST_AGENTS = "list_agents"
    
    SET_TAG = "set_tag"
    
    CREATE_TAG = "create_tag"
    GET_TAG = "get_tag"
    UPDATE_TAG = "update_tag"
    DELETE_TAG = "delete_tag"
    LIST_TAGS = "list_tags"