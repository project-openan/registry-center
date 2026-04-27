"""
Agent Management Commands

Manage agent registration, query, deregistration, etc. via HTTP calls to service API.
"""

from argparse import ArgumentParser, Namespace
from typing import Dict

from agent_registry.cli import BaseCommand, CLI, Output, cli_logger
from agent_registry.cli.client import get_client
from agent_registry.cli.exceptions import ServiceError


@CLI.register
class AgentCommand(BaseCommand):
    """Agent management command group"""
    
    @property
    def name(self) -> str:
        return "agent"
    
    @property
    def help_text(self) -> str:
        return "Agent management commands (via HTTP calls to service)"
    
    @property
    def subcommands(self) -> Dict[str, BaseCommand]:
        return {
            "list": AgentListCommand(),
            "get": AgentGetCommand(),
            "query": AgentQueryCommand(),
            "search": AgentSearchCommand(),
            "register": AgentRegisterCommand(),
            "deregister": AgentDeregisterCommand(),
        }
    
    def execute(self, args: Namespace) -> int:
        return 0


class AgentListCommand(BaseCommand):
    """List agents"""
    
    @property
    def name(self) -> str:
        return "list"
    
    @property
    def help_text(self) -> str:
        return "List registered agents"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--org", "-o", help="Filter by organization")
        parser.add_argument("--name", "-n", help="Filter by name")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output(args.format)
        
        try:
            agents = client.list_agents(
                name=args.name,
                organization=args.org
            )
            
            if not agents:
                output.info("No agents found")
                return 0
            
            if args.format == "json":
                output.print(agents)
            else:
                for agent in agents:
                    name = agent.get("name", "unknown")
                    org = agent.get("provider", {}).get("organization", "unknown")
                    url = agent.get("url", "")
                    print(f"  {name} ({org}) - {url}")
            
            return 0
        
        except ServiceError as e:
            output.error(str(e))
            return e.exit_code


class AgentGetCommand(BaseCommand):
    """Get agent details"""
    
    @property
    def name(self) -> str:
        return "get"
    
    @property
    def help_text(self) -> str:
        return "Get single agent details"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("name", help="Agent name")
        parser.add_argument("--org", "-o", required=True, help="Organization name")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="json")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output(args.format)
        
        try:
            agent = client.get_agent(args.name, args.org)
            output.print(agent, title=f"Agent: {args.name}")
            return 0
        
        except ServiceError as e:
            output.error(str(e))
            return e.exit_code


class AgentQueryCommand(BaseCommand):
    """Exact query for agents"""
    
    @property
    def name(self) -> str:
        return "query"
    
    @property
    def help_text(self) -> str:
        return "Exact query for agents"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--name", "-n", help="Agent name")
        parser.add_argument("--org", "-o", help="Organization name")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output(args.format)
        
        try:
            agents = client.list_agents(
                name=args.name,
                organization=args.org
            )
            
            if args.format == "json":
                output.print(agents)
            else:
                if not agents:
                    output.info("No agents found")
                else:
                    for agent in agents:
                        name = agent.get("name", "unknown")
                        org = agent.get("provider", {}).get("organization", "unknown")
                        print(f"  {name} ({org})")
            
            return 0
        
        except ServiceError as e:
            output.error(str(e))
            return e.exit_code


class AgentSearchCommand(BaseCommand):
    """Semantic search for agents"""
    
    @property
    def name(self) -> str:
        return "search"
    
    @property
    def help_text(self) -> str:
        return "Semantic search for agents"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("query", help="Search query")
        parser.add_argument("--top-n", "-t", type=int, default=5, help="Return count")
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output(args.format)
        
        try:
            agents = client.search_agents(args.query, args.top_n)
            
            if not agents:
                output.info(f"No agents matching '{args.query}'")
                return 0
            
            if args.format == "json":
                output.print(agents)
            else:
                output.info(f"Found {len(agents)} agents matching '{args.query}':")
                for agent in agents:
                    name = agent.get("name", "unknown")
                    org = agent.get("provider", {}).get("organization", "unknown")
                    desc = agent.get("description", "")[:50]
                    print(f"  {name} ({org}) - {desc}...")
            
            return 0
        
        except ServiceError as e:
            output.error(str(e))
            return e.exit_code


class AgentRegisterCommand(BaseCommand):
    """Register agent"""
    
    @property
    def name(self) -> str:
        return "register"
    
    @property
    def help_text(self) -> str:
        return "Register agent"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--file", "-f", required=True, help="AgentCard JSON file path")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output("text")
        
        try:
            result = client.register_agent_from_file(args.file)
            if result:
                output.success(f"Agent registered from {args.file}")
                return 0
            else:
                output.error("Registration failed")
                return 1
        
        except ServiceError as e:
            output.error(str(e))
            return e.exit_code


class AgentDeregisterCommand(BaseCommand):
    """Deregister agent"""
    
    @property
    def name(self) -> str:
        return "deregister"
    
    @property
    def help_text(self) -> str:
        return "Deregister agent"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("name", help="Agent name")
        parser.add_argument("--org", "-o", required=True, help="Organization name")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output("text")
        
        try:
            result = client.deregister_agent(args.name, args.org)
            if result:
                output.success(f"Agent '{args.name}' deregistered")
                return 0
            else:
                output.error("Deregistration failed")
                return 1
        
        except ServiceError as e:
            output.error(str(e))
            return e.exit_code