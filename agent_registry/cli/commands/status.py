"""
Service Status Command

Check Agent Registry service running status.
"""

from argparse import ArgumentParser, Namespace

from agent_registry.cli import BaseCommand, CLI, Output
from agent_registry.cli.client import get_client
from agent_registry.cli.i18n import t


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
        parser.add_argument("--debug", "-d", action="store_true", help="Show debug info")
    
    def execute(self, args: Namespace) -> int:
        client = get_client()
        output = Output(args.format)
        
        if args.debug:
            result = client.health_check_debug()
            
            print(f"[DEBUG] Service URL: {result['url']}")
            
            if result.get("ssl_info"):
                ssl_info = result["ssl_info"]
                print(f"[DEBUG] SSL Verify Mode: {ssl_info['verify_mode']}")
                print(f"[DEBUG] Check Hostname: {ssl_info['check_hostname']}")
                print(f"[DEBUG] Client Cert: {ssl_info['cert_file'] or 'None'}")
                print(f"[DEBUG] Client Key: {ssl_info['key_file'] or 'None'}")
                print(f"[DEBUG] CA Certs: {ssl_info['ca_certs'] or 'None'}")
            
            if result.get("error"):
                print(f"[DEBUG] Error: {result['error']}")
            
            status = "[Running]" if result["healthy"] else "[Not Running]"
            print(f"\nService: {result['url']}")
            print(f"Status: {status}")
            
            if args.format == "json":
                output.print(result)
            
            return 0 if result["healthy"] else 4
        
        # Normal mode
        info = client.get_service_info()
        
        if args.format == "json":
            output.print(info)
        else:
            status = "[Running]" if info["healthy"] else "[Not Running]"
            print(f"Service: {info['base_url']}")
            print(f"Status: {status}")
            print(f"HTTPS: {'Enabled' if info['https'] else 'Disabled'}")
        
        return 0 if info["healthy"] else 4