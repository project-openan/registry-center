"""
Tag Handler implementations for tag entity management.

Handlers for create/get/update/delete/list operations on independent tag entities.
"""

import json
from typing import Dict, Any
from loguru import logger

from agent_registry.internal.handlers.base_handler import BaseUDSHandler


class TagCreateHandler(BaseUDSHandler):
    """Handler for creating a new tag entity."""

    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagCreateHandler] Entering handle method with params: {params}")
        
        name = params.get('name')
        if not name:
            return {
                "success": False,
                "error": "Missing required parameter: name"
            }

        try:
            tag = registry.create_tag(name)
            if tag:
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
                return {
                    "success": False,
                    "error": "Failed to create tag",
                    "message": f"Tag '{name}' may already exist"
                }
        except Exception as e:
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

        try:
            tag = None
            if tag_id:
                tag = registry.get_tag(tag_id)
            elif name:
                tag = registry.get_tag_by_name(name)
            else:
                return {
                    "success": False,
                    "error": "Missing required parameter: tag_id or name"
                }

            if tag:
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
                return {
                    "success": False,
                    "error": "Tag not found"
                }
        except Exception as e:
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

        if not tag_id or not new_name:
            return {
                "success": False,
                "error": "Missing required parameters: tag_id and name"
            }

        try:
            success = registry.update_tag(tag_id, new_name)
            if success:
                tag = registry.get_tag(tag_id)
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
                return {
                    "success": False,
                    "error": "Failed to update tag",
                    "message": "Tag may not exist or name already taken"
                }
        except Exception as e:
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
        if not tag_id:
            return {
                "success": False,
                "error": "Missing required parameter: tag_id"
            }

        try:
            success = registry.delete_tag(tag_id)
            if success:
                return {
                    "success": True,
                    "message": f"Tag deleted successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to delete tag",
                    "message": "Tag may not exist"
                }
        except Exception as e:
            logger.error(f"Failed to delete tag: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class TagListHandler(BaseUDSHandler):
    """Handler for listing all tags."""

    def handle(self, params: Dict[str, Any], registry, config) -> Dict[str, Any]:
        logger.info(f"[TagListHandler] Entering handle method with params: {params}")

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
            
            return {
                "success": True,
                "data": {
                    "tags": tag_list,
                    "count": len(tag_list)
                }
            }
        except Exception as e:
            logger.error(f"Failed to list tags: {e}")
            return {
                "success": False,
                "error": str(e)
            }