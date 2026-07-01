import { describe, expect, it } from "vitest";

import { buildPlan } from "../scripts/print-chatgpt-developer-mode-plan.mjs";

describe("print-chatgpt-developer-mode-plan", () => {
  it("defaults to the live clouddrive origin and origin-only recommendation", () => {
    const plan = buildPlan({
      REMOTE_MCP_PUBLIC_BASE_URL: "https://worker.example.test",
      ORIGIN_BASE_URL: "",
      WORKER_API_TOKEN: "",
    });

    expect(plan.origin_base_url).toBe("https://clouddrive.neonbutterfly.net");
    expect(plan.worker_auth_mode).toBe("origin-only");
    expect(plan.recommended_worker_auth_mode).toBe("origin-only");
    expect(plan.mcp_url).toBe("https://worker.example.test/mcp");
    expect(plan.health_url).toBe("https://worker.example.test/healthz");
  });

  it("warns when a worker token is still configured", () => {
    const plan = buildPlan({
      REMOTE_MCP_PUBLIC_BASE_URL: "https://worker.example.test",
      ORIGIN_BASE_URL: "https://clouddrive.neonbutterfly.net",
      WORKER_API_TOKEN: "bootstrap-token",
    });

    expect(plan.worker_auth_mode).toBe("worker-api-token");
    expect(plan.recommendation).toContain("Unset WORKER_API_TOKEN");
  });
});
