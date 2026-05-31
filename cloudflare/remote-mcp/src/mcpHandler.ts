import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

export type McpHandlerOptions = {
  route?: string;
};

export function createMcpHandler(server: McpServer, options: McpHandlerOptions = {}) {
  const route = options.route ?? "/mcp";

  return async (request: Request) => {
    const url = new URL(request.url);
    if (url.pathname !== route) {
      return new Response("Not Found", { status: 404 });
    }

    if (request.method === "GET") {
      return new Response("Method Not Allowed", {
        status: 405,
        headers: {
          Allow: "POST, DELETE",
        },
      });
    }

    const transport = new WebStandardStreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });

    try {
      await server.connect(transport);
      return await transport.handleRequest(request);
    } catch (error) {
      console.error("MCP handler error:", error);
      return new Response(
        JSON.stringify({
          jsonrpc: "2.0",
          error: {
            code: -32603,
            message: error instanceof Error ? error.message : "Internal server error",
          },
          id: null,
        }),
        {
          status: 500,
          headers: {
            "Content-Type": "application/json",
          },
        },
      );
    }
  };
}
