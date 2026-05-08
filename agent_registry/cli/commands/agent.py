"""
Agent Management Commands

Manage agent via internal UDS service.
"""

from argparse import ArgumentParser, Namespace
from typing import Dict

from agent_registry.cli import BaseCommand, CLI, Output
from agent_registry.cli.uds_client import get_uds_client


@CLI.register
class AgentCommand(BaseCommand):
    """Agent management command group"""
    
    @property
    def name(self) -> str:
        return "agent"
    
    @property
    def help_text(self) -> str:
        return "Agent management commands via internal UDS service"
    
    @property
    def subcommands(self) -> Dict[str, BaseCommand]:
        return {
            "approval": ApprovalCommand(),
            "uds-list": UDSListCommand(),
            "uds-get": UDSGetCommand(),
            "add-tags": AddTagsCommand(),
        }
    
    def execute(self, args: Namespace) -> int:
        return 0


class UDSGetCommand(BaseCommand):
    """Get single agent metadata via UDS"""

    @property
    def name(self) -> str:
        return "uds-get"

    @property
    def help_text(self) -> str:
        return "Get agent details (agentcard, status, tag)"

    @property
    def display_config(self) -> Dict:
        return {
            'table_fields': ['agent_name', 'organization', 'status', 'tags', 'created_at', 'updated_at'],
            'separate_fields': ['agentcard'],
            'field_labels': {
                'agent_name': 'Agent Name',
                'organization': 'Organization',
                'status': 'Status',
                'tags': 'Tags',
                'created_at': 'Created At',
                'updated_at': 'Updated At',
                'agentcard': 'AgentCard JSON',
            }
        }

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--agent-name", "-n", required=True, help="Agent name")
        parser.add_argument("--org", "-o", required=True, help="Organization name")
        parser.add_argument("--format", "-f", choices=["text", "json", "table"], default="table")

    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.get_agent(args.agent_name, args.org)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            data = result.get("data", {})
            
            flattened_data = {
                'agent_name': args.agent_name,
                'organization': args.org,
                'status': data.get('status', 'published'),
                'tags': ', '.join(data.get('tag', [])) or 'None',
                'created_at': data.get('created_at', 'N/A'),
                'updated_at': data.get('updated_at', 'N/A'),
                'agentcard': data.get('agentcard', {}),
            }
            
            print(self.format_output(flattened_data, title=f"Agent: {args.agent_name}"))
            return 0
        else:
            output.error(result.get("error", "Query failed"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class UDSListCommand(BaseCommand):
    """List all agents metadata via UDS"""

    @property
    def name(self) -> str:
        return "uds-list"

    @property
    def help_text(self) -> str:
        return "List all agents (agent_name, organization, status, tag)"

    @property
    def display_config(self) -> Dict:
        return {
            'table_fields': ['agent_name', 'organization', 'status', 'tags'],
            'field_labels': {
                'agent_name': 'Agent Name',
                'organization': 'Organization',
                'status': 'Status',
                'tags': 'Tags',
            }
        }

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--format", "-f", choices=["text", "json", "table"], default="table")

    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.list_agents()

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            agents = result.get("data", {}).get("agents", [])
            if not agents:
                output.info("No agents found")
                return 0
            
            flattened_agents = []
            for agent in agents:
                flattened_agents.append({
                    'agent_name': agent.get("agent_name", "unknown"),
                    'organization': agent.get("organization", "unknown"),
                    'status': agent.get("status", "unknown"),
                    'tags': ', '.join(agent.get("tag", [])) or 'None',
                })
            
            print(self.format_list_output(flattened_agents, title=f"Agents List ({len(agents)} total)"))
            return 0
        else:
            output.error(result.get("error", "Query failed"))
            return 1


class ApprovalCommand(BaseCommand):
    """Approve registered agent via internal UDS service"""

    @property
    def name(self) -> str:
        return "approval"

    @property
    def help_text(self) -> str:
        return "Approve registered agent (requires agent_approval_enabled=true)"

    @property
    def display_config(self) -> Dict:
        return {
            'table_fields': ['agent_name', 'organization', 'status', 'approved'],
            'field_labels': {
                'agent_name': 'Agent Name',
                'organization': 'Organization',
                'status': 'Status',
                'approved': 'Approved',
            }
        }

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--agent-name", "-n", required=True, help="Agent name")
        parser.add_argument("--org", "-o", required=True, help="Organization name")
        parser.add_argument("--format", "-f", choices=["text", "json", "table"], default="table")

    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        result = client.approval_agent(args.agent_name, args.org)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            data = result.get("data", {})
            
            flattened_data = {
                'agent_name': args.agent_name,
                'organization': args.org,
                'status': data.get('status', 'published'),
                'approved': 'Yes',
            }
            
            print(self.format_output(flattened_data, title="Approval Result"))
            return 0
        else:
            output.error(result.get("error", "Approval failed"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1


class AddTagsCommand(BaseCommand):
    """Add tags to agent via UDS"""

    @property
    def name(self) -> str:
        return "add-tags"

    @property
    def help_text(self) -> str:
        return "Add tags to agent (tags will be appended and deduplicated)"

    @property
    def display_config(self) -> Dict:
        return {
            'table_fields': ['agent_name', 'organization', 'tags_added', 'current_tags'],
            'field_labels': {
                'agent_name': 'Agent Name',
                'organization': 'Organization',
                'tags_added': 'Tags Added',
                'current_tags': 'Current Tags',
            }
        }

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--agent-name", "-n", required=True, help="Agent name")
        parser.add_argument("--org", "-o", required=True, help="Organization name")
        parser.add_argument("--tags", "-t", required=True, help="Tags (comma-separated)")
        parser.add_argument("--format", "-f", choices=["text", "json", "table"], default="table")

    def execute(self, args: Namespace) -> int:
        output = Output(args.format)
        client = get_uds_client()

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        if not tags:
            output.error("No valid tags provided")
            return 1

        result = client.add_tags(args.agent_name, args.org, tags)

        if args.format == "json":
            output.print(result)
            return 0 if result.get("success") else 1

        if result.get("success"):
            data = result.get("data", {})
            
            flattened_data = {
                'agent_name': args.agent_name,
                'organization': args.org,
                'tags_added': ', '.join(tags),
                'current_tags': ', '.join(data.get('tag', [])) or 'None',
            }
            
            print(self.format_output(flattened_data, title="Tags Added"))
            return 0
        else:
            output.error(result.get("error", "Add tags failed"))
            if result.get("message"):
                print(f"  Message: {result['message']}")
            return 1