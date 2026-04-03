from enum import Enum


class InterfaceType(Enum):
    """认证失败原因枚举"""
    DECRYPT = "decrypt"
    AUDIT = "audit"
    AUTHENTICATE = "authenticate"
    INSERT = "insert"
    QUERY = "query"