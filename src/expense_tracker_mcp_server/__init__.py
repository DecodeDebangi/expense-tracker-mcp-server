from expense_tracker_mcp_server.server import mcp

def main() -> None:
    mcp.run(transport="sse", host="0.0.0.0", port=8000)

__all__ = ["mcp", "main"]
