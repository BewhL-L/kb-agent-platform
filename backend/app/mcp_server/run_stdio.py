"""
MCP stdio 启动（用于桌面客户端/IDE 以子进程方式接入）
  python -m app.mcp_server.run_stdio
"""
from .server import build_server


def main() -> None:
    mcp = build_server()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
