#!/usr/bin/env python3
"""
mcp_server.py
MCP (Model Context Protocol) Server for BoramClaw

Claude Desktop과 통합하여 BoramClaw의 모든 기능을 Claude Desktop에서 사용 가능하게 함.
stdio 기반 JSON-RPC 2.0 프로토콜 구현.

Usage:
    python3 mcp_server.py

Claude Desktop 설정:
    ~/.config/Claude/claude_desktop_config.json 에 추가:
    {
      "mcpServers": {
        "boramclaw": {
          "command": "python3",
          "args": ["/Users/boram/BoramClaw/mcp_server.py"]
        }
      }
    }
"""
import sys
import json
import logging
from pathlib import Path
from typing import Any, Optional

# BoramClaw 모듈 import
sys.path.insert(0, str(Path(__file__).parent))
from main import ToolExecutor

# 로깅 설정 (stderr로 출력, stdout은 MCP 프로토콜용으로 예약)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)


class MCPServer:
    """MCP 서버 구현"""

    def __init__(self):
        self.server_info = {
            "name": "boramclaw",
            "version": "1.0.0",
        }
        self.capabilities = {
            "tools": {},
        }
        self.tool_executor: Optional[ToolExecutor] = None

    def initialize_tools(self):
        """BoramClaw 툴 로더 초기화"""
        try:
            from config import BoramClawConfig

            config = BoramClawConfig.from_env()
            self.tool_executor = ToolExecutor(
                workdir=config.tool_workdir,
                default_timeout_seconds=config.tool_timeout_seconds,
                custom_tool_dir=config.custom_tool_dir,
                schedule_file=config.schedule_file,
                strict_workdir_only=config.strict_workdir_only,
            )
            logger.info(f"Loaded {len(self.tool_executor.describe_tools())} tools")
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            self.tool_executor = None

    def handle_request(self, request: dict) -> dict:
        """
        JSON-RPC 2.0 요청 처리

        Args:
            request: JSON-RPC 요청 dict

        Returns:
            JSON-RPC 응답 dict
        """
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        logger.info(f"Handling request: method={method}, id={request_id}")

        try:
            if method == "initialize":
                result = self.handle_initialize(params)
            elif method == "tools/list":
                result = self.handle_tools_list(params)
            elif method == "tools/call":
                result = self.handle_tools_call(params)
            elif method == "ping":
                result = {"status": "ok"}
            else:
                return self.error_response(request_id, -32601, f"Method not found: {method}")

            return self.success_response(request_id, result)

        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            return self.error_response(request_id, -32603, f"Internal error: {str(e)}")

    def handle_initialize(self, params: dict) -> dict:
        """
        initialize 요청 처리

        Args:
            params: {"protocolVersion": "2024-11-05", "capabilities": {...}, "clientInfo": {...}}

        Returns:
            {"protocolVersion": "...", "capabilities": {...}, "serverInfo": {...}}
        """
        protocol_version = params.get("protocolVersion", "2024-11-05")
        client_info = params.get("clientInfo", {})

        logger.info(f"Initialize: protocol={protocol_version}, client={client_info}")

        # 툴 로더 초기화
        self.initialize_tools()

        return {
            "protocolVersion": protocol_version,
            "capabilities": self.capabilities,
            "serverInfo": self.server_info,
        }

    def handle_tools_list(self, params: dict) -> dict:
        """
        tools/list 요청 처리

        Returns:
            {"tools": [{"name": "...", "description": "...", "inputSchema": {...}}, ...]}
        """
        if not self.tool_executor:
            return {"tools": []}

        tools = []
        for tool_info in self.tool_executor.describe_tools():
            # BoramClaw 툴 스펙을 MCP 포맷으로 변환
            mcp_tool = {
                "name": tool_info["name"],
                "description": tool_info["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": tool_info.get("properties", {}),
                    "required": tool_info.get("required", []),
                },
            }
            tools.append(mcp_tool)

        logger.info(f"Returning {len(tools)} tools")
        return {"tools": tools}

    def handle_tools_call(self, params: dict) -> dict:
        """
        tools/call 요청 처리

        Args:
            params: {"name": "tool_name", "arguments": {...}}

        Returns:
            {"content": [{"type": "text", "text": "..."}], "isError": false}
        """
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        logger.info(f"Calling tool: {tool_name} with args: {arguments}")

        if not self.tool_executor:
            return {
                "content": [{"type": "text", "text": "Tool executor not initialized"}],
                "isError": True,
            }

        try:
            result_text, is_error = self.tool_executor.run_tool(tool_name, arguments)

            return {
                "content": [{"type": "text", "text": result_text}],
                "isError": is_error,
            }
        except Exception as e:
            logger.error(f"Tool execution failed: {e}", exc_info=True)
            return {
                "content": [{"type": "text", "text": f"Tool execution error: {str(e)}"}],
                "isError": True,
            }

    def success_response(self, request_id: Any, result: dict) -> dict:
        """JSON-RPC 2.0 성공 응답 생성"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    def error_response(self, request_id: Any, code: int, message: str) -> dict:
        """JSON-RPC 2.0 에러 응답 생성"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


def main():
    """MCP 서버 메인 루프 - stdio 기반 JSON-RPC"""
    logger.info("BoramClaw MCP Server starting...")

    server = MCPServer()

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = server.handle_request(request)

                # stdout으로 응답 전송 (JSON-RPC)
                print(json.dumps(response), flush=True)

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                error_resp = server.error_response(None, -32700, "Parse error")
                print(json.dumps(error_resp), flush=True)
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                error_resp = server.error_response(None, -32603, f"Internal error: {str(e)}")
                print(json.dumps(error_resp), flush=True)

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
