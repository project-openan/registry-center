"""
Tag Handler implementations for tag entity management.

Handlers for create/get/update/delete/list operations on independent tag entities.
All operations include audit logging for security compliance.
"""

import asyncio
import json
from typing import Dict, Any
from loguru import logger

from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationName, OperationResult, OperatorObject


class TagCreateHandler(BaseUDSHandler):
    """Handler for creating a new tag entity."""

    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagCreateHandler] Entering handle method with params: {params}")
        
        name = params.get('name')
        user_name = params.get('user_name', 'admin')
        
        details = {
            "tagName": name
        }
        
        audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)
        
        if not name:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.CREATE_TAG,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return {
                "success": False,
                "error": "Missing required parameter: name"
            }

        try:
            tag = registry.create_tag(name)
            if tag:
                details["tagId"] = tag.tag_id
                details["createdAt"] = tag.created_at
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.CREATE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.SUCCESS,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.info(f"Tag created: {name} (ID: {tag.tag_id})")
                return {
                    "success": True,
                    "data": {
                        "tag_id": tag.tag_id,
                        "name": tag.name,
                        "created_at": tag.created_at,
                        "updated_at": tag.updated_at
                    },
                    "message": f"Tag '{name}' created successfully"
                }
            else:
                details["reason"] = "Tag may already exist"
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.CREATE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.warning(f"Failed to create tag: {name} (may already exist)")
                return {
                    "success": False,
                    "error": "Failed to create tag",
                    "message": f"Tag '{name}' may already exist"
                }
        except Exception as e:
            details["error"] = str(e)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.CREATE_TAG,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.error(f"Failed to create tag: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class TagGetHandler(BaseUDSHandler):
    """Handler for getting a tag by tag_id or name."""

    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagGetHandler] Entering handle method with params: {params}")
        
        tag_id = params.get('tag_id')
        name = params.get('name')
        user_name = params.get('user_name', 'admin')
        
        details = {
            "tagId": tag_id,
            "tagName": name
        }
        
        audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)

        try:
            tag = None
            if tag_id:
                tag = registry.get_tag(tag_id)
            elif name:
                tag = registry.get_tag_by_name(name)
            else:
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.GET_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                return {
                    "success": False,
                    "error": "Missing required parameter: tag_id or name"
                }

            if tag:
                details["found"] = True
                details["actualTagId"] = tag.tag_id
                details["actualTagName"] = tag.name
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.GET_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.SUCCESS,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                return {
                    "success": True,
                    "data": {
                        "tag_id": tag.tag_id,
                        "name": tag.name,
                        "created_at": tag.created_at,
                        "updated_at": tag.updated_at
                    }
                }
            else:
                details["found"] = False
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.GET_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.warning(f"Tag not found: tag_id={tag_id}, name={name}")
                return {
                    "success": False,
                    "error": "Tag not found"
                }
        except Exception as e:
            details["error"] = str(e)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.GET_TAG,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.error(f"Failed to get tag: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class TagUpdateHandler(BaseUDSHandler):
    """Handler for updating a tag."""

    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagUpdateHandler] Entering handle method with params: {params}")
        
        tag_id = params.get('tag_id')
        new_name = params.get('name')
        user_name = params.get('user_name', 'admin')
        
        details = {
            "tagId": tag_id,
            "newTagName": new_name
        }
        
        audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)

        if not tag_id or not new_name:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAG,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return {
                "success": False,
                "error": "Missing required parameters: tag_id and name"
            }

        try:
            # Get old tag name for audit log
            old_tag = registry.get_tag(tag_id)
            if old_tag:
                details["oldTagName"] = old_tag.name
            
            success = registry.update_tag(tag_id, new_name)
            if success:
                tag = registry.get_tag(tag_id)
                details["updatedAt"] = tag.updated_at
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.UPDATE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.SUCCESS,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.info(f"Tag updated: {tag_id} -> {new_name}")
                return {
                    "success": True,
                    "data": {
                        "tag_id": tag.tag_id,
                        "name": tag.name,
                        "updated_at": tag.updated_at
                    },
                    "message": f"Tag updated successfully"
                }
            else:
                details["reason"] = "Tag may not exist or name already taken"
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.UPDATE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.warning(f"Failed to update tag: {tag_id} -> {new_name}")
                return {
                    "success": False,
                    "error": "Failed to update tag",
                    "message": "Tag may not exist or name already taken"
                }
        except Exception as e:
            details["error"] = str(e)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.UPDATE_TAG,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.error(f"Failed to update tag: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class TagDeleteHandler(BaseUDSHandler):
    """Handler for deleting a tag."""

    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagDeleteHandler] Entering handle method with params: {params}")
        
        tag_id = params.get('tag_id')
        user_name = params.get('user_name', 'admin')
        
        details = {
            "tagId": tag_id
        }
        
        audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)
        
        if not tag_id:
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.DELETE_TAG,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            return {
                "success": False,
                "error": "Missing required parameter: tag_id"
            }

        try:
            # Get tag to retrieve tag name
            tag = registry.get_tag(tag_id)
            if not tag:
                details["reason"] = "Tag not found"
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.DELETE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.warning(f"Tag not found for deletion: {tag_id}")
                return {
                    "success": False,
                    "error": "Tag not found",
                    "message": f"Tag with ID '{tag_id}' does not exist"
                }
            
            tag_name = tag.name
            details["tagName"] = tag_name
            
            # Check if any agents are using this tag
            agents_using_tag = registry.find_agents_by_tag(tag_name)
            if agents_using_tag:
                agent_list = [
                    f"{agent.name} ({agent.provider.organization})"
                    for agent in agents_using_tag
                ]
                details["agentsUsingTag"] = agent_list
                details["agentCount"] = len(agents_using_tag)
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.DELETE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.warning(f"Cannot delete tag '{tag_name}': used by {len(agents_using_tag)} agents")
                return {
                    "success": False,
                    "error": "Tag is in use",
                    "message": f"Cannot delete tag '{tag_name}' because it is used by {len(agents_using_tag)} agents: {', '.join(agent_list)}"
                }
            
            # No agents using this tag, proceed with deletion
            success = registry.delete_tag(tag_id)
            if success:
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.DELETE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.SUCCESS,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.info(f"Tag deleted successfully: {tag_name} ({tag_id})")
                return {
                    "success": True,
                    "message": f"Tag '{tag_name}' deleted successfully"
                }
            else:
                details["reason"] = "Deletion failed"
                asyncio.run(audit_handle.handle({
                    "operation_name": OperationName.DELETE_TAG,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.TAG,
                    "details": details,
                    "client_ip": "internal",
                    "user_name": user_name
                }))
                logger.error(f"Failed to delete tag: {tag_id}")
                return {
                    "success": False,
                    "error": "Failed to delete tag",
                    "message": "Tag deletion failed"
                }
        except Exception as e:
            details["error"] = str(e)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.DELETE_TAG,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.error(f"Failed to delete tag: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class TagListHandler(BaseUDSHandler):
    """Handler for listing all tags."""

    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagListHandler] Entering handle method with params: {params}")
        
        user_name = params.get('user_name', 'admin')
        
        details = {}
        
        audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)

        try:
            tags = registry.list_tags()
            tag_list = [
                {
                    "tag_id": tag.tag_id,
                    "name": tag.name,
                    "created_at": tag.created_at,
                    "updated_at": tag.updated_at
                }
                for tag in tags
            ]
            
            details["tagCount"] = len(tag_list)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.LIST_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.SUCCESS,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.info(f"Listed {len(tag_list)} tags")
            
            return {
                "success": True,
                "data": {
                    "tags": tag_list,
                    "count": len(tag_list)
                }
            }
        except Exception as e:
            details["error"] = str(e)
            asyncio.run(audit_handle.handle({
                "operation_name": OperationName.LIST_TAGS,
                "level": LogLevel.MINOR,
                "result": OperationResult.FAILURE,
                "object_name": OperatorObject.TAG,
                "details": details,
                "client_ip": "internal",
                "user_name": user_name
            }))
            logger.error(f"Failed to list tags: {e}")
            return {
                "success": False,
                "error": str(e)
            }