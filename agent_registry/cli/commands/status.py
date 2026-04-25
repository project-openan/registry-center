"""
Service Status Command

Check Agent Registry service running status.
"""

from argparse import ArgumentParser, Namespace

from agent_registry.cli import BaseCommand, CLI, Output
from agent_registry.cli.client import get_client


@CLI.register
class StatusCommand(BaseCommand):
    """Service status command"""
    
    @property
    def name(self) -> str:
        return "status"
    
    @property
    def help_text(self) -> str:
        return "View service status"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output(args.format)
        
        info = client.get_service_info()
        
        if args.format == "json":
            output.print(info)
        else:
            status = "[Running]" if info["healthy"] else "[Not Running]"
            print(f"Service: {info['base_url']}")
            print(f"Status: {status}")
            print(f"HTTPS: {'Enabled' if info['https'] else 'Disabled'}")
        
        return 0 if info["healthy"] else 4