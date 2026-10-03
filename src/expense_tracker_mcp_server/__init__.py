from expense_tracker_mcp_server.server import mcp

def main() -> None:
    mcp.run()

__all__ = ["mcp", "main"]
