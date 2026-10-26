"""
MCP Streamable-HTTP 启动（远程 Agent 通过 HTTP 接入）
  python -m app.mcp_server.run_http --host 0.0.0.0 --port 8001
默认接入地址：http://localhost:8001/mcp
"""
import argparse

from .server import build_server


def main() -> None:
    p = argparse.ArgumentParser(description="MCP HTTP Server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8001)
    args = p.parse_args()

    mcp = build_server(host=args.host, port=args.port)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
