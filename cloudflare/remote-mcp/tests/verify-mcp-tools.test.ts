import { describe, expect, it } from "vitest";

import {
  DEFAULT_EXPECTED_TOOLS,
  buildAuthHeaders,
  buildDerivedUrls,
  parseJsonObject,
  resolveConfig,
  summarizeProbeResult,
} from "../scripts/verify-mcp-tools.mjs";

describe("verify-mcp-tools helpers", () => {
  it("derives mcp and health URLs from a base URL", () => {
    expect(buildDerivedUrls("https://worker.example.test")).toEqual({
      mcpUrl: "https://worker.example.test/mcp",
      healthUrl: "https://worker.example.test/healthz",
    });
  });

  it("parses JSON object arguments and rejects non-objects", () => {
    expect(parseJsonObject('{"limit":3}', "--probe-args")).toEqual({ limit: 3 });
    expect(() => parseJsonObject("[]", "--probe-args")).toThrow(
      "--probe-args must decode to a JSON object",
    );
  });

  it("builds bearer auth headers only when a token is present", () => {
    expect(buildAuthHeaders("")).toEqual({});
    expect(buildAuthHeaders(" worker-secret ")).toEqual({
      Authorization: "Bearer worker-secret",
    });
  });

  it("resolves config from a public base URL and defaults the expected tools", () => {
    const config = resolveConfig(
      {
        mcpUrl: "",
        baseUrl: "https://worker.example.test",
        token: "",
        probeTool: "",
        probeArgsRaw: "{}",
        expectToolsCsv: "",
        skipHealth: false,
        json: true,
      },
      {},
    );

    expect(config.mcpUrl).toBe("https://worker.example.test/mcp");
    expect(config.healthUrl).toBe("https://worker.example.test/healthz");
    expect(config.probeTool).toBe("get_icloud_system_status");
    expect(config.expectedTools).toEqual(DEFAULT_EXPECTED_TOOLS);
    expect(config.json).toBe(true);
  });

  it("accepts explicit tool expectations and probe args", () => {
    const config = resolveConfig(
      {
        mcpUrl: "https://worker.example.test/mcp",
        baseUrl: "",
        token: "",
        probeTool: "search_icloud_files",
        probeArgsRaw: '{"query":"appeal"}',
        expectToolsCsv: "search_icloud_files,get_icloud_note",
        skipHealth: true,
        json: false,
      },
      {},
    );

    expect(config.expectedTools).toEqual(["search_icloud_files", "get_icloud_note"]);
    expect(config.probeArgs).toEqual({ query: "appeal" });
    expect(config.skipHealth).toBe(true);
  });

  it("summarizes structured tool results without dumping huge payloads", () => {
    const summary = summarizeProbeResult({
      isError: false,
      structuredContent: { status: "ok" },
      content: [
        { type: "text", text: "hello world" },
        { type: "resource_link", uri: "file://note.md" },
      ],
    });

    expect(summary).toEqual({
      isError: false,
      structuredContent: { status: "ok" },
      contentPreview: ["hello world", "[resource_link]"],
    });
  });
});
