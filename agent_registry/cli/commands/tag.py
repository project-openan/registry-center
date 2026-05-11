"""
Tag Management Commands

Manage agent tags via UDS (Unix Domain Socket) internal service.
"""

from argparse import ArgumentParser, Namespace
from typing import Dict

from agent_registry.cli import BaseCommand, CLI, Output
from agent_registry.cli.uds_client import get_uds_client


@CLI.register
class TagCommand(BaseCommand):
    """Tag management command group"""
    
    @property
    def name(self) -> str:
        return "tag"
    
    @property
    def help_text(self) -> str:
        return "Agent tag management via UDS interface"
    
    @property
    def subcommands(self) -> Dict[str, BaseCommand]:
        return {
            "add": TagAddCommand(),
            "remove": TagRemoveCommand(),
            "update": TagUpdateCommand(),
            "get": TagGetCommand(),
            "list": TagListCommand(),
        }
    
    def execute(self, args: Namespace) -> int:
        return 0


class TagAddCommand(BaseCommand):
    """Add tags to agent"""
    
    @property
    def name(self) -> str:
        return "add"
    
    @property
    def help_text(self) -> str:
        return "Add tags to agent"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("name", help="Agent name")
        parser.add_argument("organization", help="Organization name")
        parser.add_argument("--tags", "-t", required=True, nargs='+', help="Tags to add (space-separated)")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.add_tags(args.name, args.organization, args.tags)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            output.success(f"Tags added successfully")
            tags = result.get("data", {}).get("tags", [])
            if tags:
                output.info(f"Current tags: {', '.join(tags)}")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagRemoveCommand(BaseCommand):
    """Remove tags from agent"""
    
    @property
    def name(self) -> str:
        return "remove"
    
    @property
    def help_text(self) -> str:
        return "Remove tags from agent"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("name", help="Agent name")
        parser.add_argument("organization", help="Organization name")
        parser.add_argument("--tags", "-t", required=True, nargs='+', help="Tags to remove (space-separated)")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.remove_tags(args.name, args.organization, args.tags)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            output.success(f"Tags removed successfully")
            tags = result.get("data", {}).get("tags", [])
            if tags:
                output.info(f"Remaining tags: {', '.join(tags)}")
            else:
                output.info(f"No tags remaining")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagUpdateCommand(BaseCommand):
    """Update agent tags (full replacement)"""
    
    @property
    def name(self) -> str:
        return "update"
    
    @property
    def help_text(self) -> str:
        return "Update agent tags (full replacement)"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("name", help="Agent name")
        parser.add_argument("organization", help="Organization name")
        parser.add_argument("--tags", "-t", required=True, nargs='+', help="New tags (space-separated)")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.update_tags(args.name, args.organization, args.tags)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            output.success(f"Tags updated successfully")
            tags = result.get("data", {}).get("tags", [])
            if tags:
                output.info(f"New tags: {', '.join(tags)}")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagGetCommand(BaseCommand):
    """Get agent tags"""
    
    @property
    def name(self) -> str:
        return "get"
    
    @property
    def help_text(self) -> str:
        return "Get agent tags"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("name", help="Agent name")
        parser.add_argument("organization", help="Organization name")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.get_tags(args.name, args.organization)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            tags = result.get("data", {}).get("tags", [])
            if tags:
                output.info(f"Tags for '{args.name}': {', '.join(tags)}")
            else:
                output.info(f"Agent '{args.name}' has no tags")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class TagListCommand(BaseCommand):
    """List agents by tag"""
    
    @property
    def name(self) -> str:
        return "list"
    
    @property
    def help_text(self) -> str:
        return "List agents with specific tag"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("tag", help="Tag to search")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.find_by_tag(args.tag)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            agents = result.get("data", {}).get("agents", [])
            count = result.get("data", {}).get("count", 0)

            if agents:
                output.info(f"Found {count} agents with tag '{args.tag}':")
                for agent in agents:
                    name = agent.get("agent_name", "unknown")
                    org = agent.get("organization", "unknown")
                    desc = agent.get("description", "")
                    if desc:
                        desc = desc[:50] + "..." if len(desc) > 50 else desc
                    print(f"  {name} ({org}) - {desc}")
            else:
                output.info(f"No agents found with tag '{args.tag}'")
            return 0
        else:
            output.error(result.get("error", "Unknown error"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1