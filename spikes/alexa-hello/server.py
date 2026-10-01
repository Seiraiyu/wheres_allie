"""Phase 0 spike: smallest MCP server Alexa+ can call. Throwaway; not the product."""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("wheres-allie-hello")


@mcp.tool()
def where_is(pet: str = "Allie") -> str:
    """Say where the pet is right now. Spike: always the same canned answer."""
    return f"{pet} is on her bed in the master bedroom. This is spike data."


if __name__ == "__main__":
    mcp.run("streamable-http", host="0.0.0.0", port=8765, stateless_http=True, json_response=True)
