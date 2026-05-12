"""
Tag Entity Management Commands

Manage tag entities (independent tag table) via UDS internal service.
"""

from argparse import ArgumentParser, Namespace
from typing import Dict

from agent_registry.cli import BaseCommand, CLI, Output
from agent_registry.cli.uds_client import get_uds_client


@CLI.register
class TagCommand(BaseCommand):
    """Tag entity management command group"""
    
    @property
    def name(self) -> str:
        return "tag"
    
    @property
    def help_text(self) -> str:
        return "Tag entity management via UDS interface"
    
    @property
    def subcommands(self) -> Dict[str, BaseCommand]:
        return {
            "create": TagCreateCommand(),
            "get": TagGetCommand(),
            "update": TagUpdateCommand(),
            "delete": TagDeleteCommand(),
            "list": TagListCommand(),
        }
    
    def execute(self, args: Namespace) -> int:
        return 0


class TagCreateCommand(BaseCommand):
    """Create a new tag entity"""
    
    @property
    def name(self) -> str:
        return "create"
    
    @property
    def help_text(self) -> str:
        return "Create a new tag entity"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--name", "-n", required=True, help="Tag name")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.create_tag(args.name)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            output.success(f"Tag created successfully")
            data = result.get("data", {})
            output.info(f"Tag ID: {data.get('tag_id', 'unknown')}")
            output.info(f"Tag Name: {data.get('name', 'unknown')}")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagGetCommand(BaseCommand):
    """Get tag entity by ID or name"""
    
    @property
    def name(self) -> str:
        return "get"
    
    @property
    def help_text(self) -> str:
        return "Get tag entity by ID or name"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--id", "-i", help="Tag ID")
        parser.add_argument("--name", "-n", help="Tag name")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        if not args.id and not args.name:
            output.error("Must provide either --id or --name")
            return 1

        result = client.get_tag(tag_id=args.id, name=args.name)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            data = result.get("data", {})
            output.info(f"Tag ID: {data.get('tag_id', 'unknown')}")
            output.info(f"Tag Name: {data.get('name', 'unknown')}")
            output.info(f"Created: {data.get('created_at', 'unknown')}")
            output.info(f"Updated: {data.get('updated_at', 'unknown')}")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagUpdateCommand(BaseCommand):
    """Update tag entity name"""
    
    @property
    def name(self) -> str:
        return "update"
    
    @property
    def help_text(self) -> str:
        return "Update tag entity name"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--id", "-i", required=True, help="Tag ID")
        parser.add_argument("--name", "-n", required=True, help="New tag name")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.update_tag(args.id, args.name)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            output.success(f"Tag updated successfully")
            data = result.get("data", {})
            output.info(f"Tag ID: {data.get('tag_id', 'unknown')}")
            output.info(f"New Name: {data.get('name', 'unknown')}")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagDeleteCommand(BaseCommand):
    """Delete tag entity"""
    
    @property
    def name(self) -> str:
        return "delete"
    
    @property
    def help_text(self) -> str:
        return "Delete tag entity"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--id", "-i", required=True, help="Tag ID")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.delete_tag(args.id)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            output.success(f"Tag deleted successfully")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagListCommand(BaseCommand):
    """List all tag entities"""
    
    @property
    def name(self) -> str:
        return "list"
    
    @property
    def help_text(self) -> str:
        return "List all tag entities"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.list_tags()

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            tags = result.get("data", {}).get("tags", [])
            count = result.get("data", {}).get("count", 0)

            if tags:
                output.info(f"Found {count} tags:")
                for tag in tags:
                    tag_id = tag.get("tag_id", "unknown")
                    name = tag.get("name", "unknown")
                    created = tag.get("created_at", "")
                    print(f"  {tag_id}: {name} (created: {created[:19] if created else 'unknown'})")
            else:
                output.info(f"No tags found")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1