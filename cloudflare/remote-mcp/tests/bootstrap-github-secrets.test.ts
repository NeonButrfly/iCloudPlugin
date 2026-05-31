import { describe, expect, it } from "vitest";

import {
  DEFAULT_REPO,
  parseArgs,
  resolveBootstrapPlan,
} from "../scripts/bootstrap-github-secrets.mjs";

describe("bootstrap-github-secrets", () => {
  it("parses command-line overrides", () => {
    const parsed = parseArgs([
      "--repo",
      "example/repo",
      "--secrets-file",
      ".dev.vars",
      "--public-base-url",
      "https://worker.example.test",
      "--apply",
      "--json",
    ]);

    expect(parsed).toEqual({
      repo: "example/repo",
      secretsFile: ".dev.vars",
      publicBaseUrl: "https://worker.example.test",
      apply: true,
      json: true,
    });
  });

  it("reports missing required values while preserving optional entries", () => {
    const plan = resolveBootstrapPlan(
      { repo: DEFAULT_REPO, secretsFile: "", publicBaseUrl: "", apply: false, json: false },
      {
        ORIGIN_BASE_URL: "https://origin.example.test",
        WORKER_API_TOKEN: "worker-secret",
      },
    );

    expect(plan.repo).toBe(DEFAULT_REPO);
    expect(plan.can_apply).toBe(false);
    expect(plan.missing_required).toEqual([
      "CLOUDFLARE_API_TOKEN",
      "REMOTE_MCP_ORIGIN_API_TOKEN",
    ]);

    const entryMap = new Map(
      plan.entries.map((entry: (typeof plan.entries)[number]) => [entry.target_name, entry]),
    );
    expect(entryMap.get("REMOTE_MCP_ORIGIN_BASE_URL")?.present).toBe(true);
    expect(entryMap.get("REMOTE_MCP_WORKER_API_TOKEN")?.present).toBe(true);
    expect(entryMap.get("REMOTE_MCP_PUBLIC_BASE_URL")?.kind).toBe("variable");
  });

  it("accepts a public base URL override as a workflow-ready value", () => {
    const plan = resolveBootstrapPlan(
      {
        repo: DEFAULT_REPO,
        secretsFile: "",
        publicBaseUrl: "https://worker.example.test",
        apply: false,
        json: false,
      },
      {
        CLOUDFLARE_API_TOKEN: "cf-token",
        ORIGIN_BASE_URL: "https://origin.example.test",
        ORIGIN_API_TOKEN: "origin-token",
      },
    );

    expect(plan.can_apply).toBe(true);
    const publicBaseUrlEntry = plan.entries.find(
      (entry: (typeof plan.entries)[number]) =>
        entry.target_name === "REMOTE_MCP_PUBLIC_BASE_URL",
    );
    expect(publicBaseUrlEntry?.present).toBe(true);
    expect(publicBaseUrlEntry?.kind).toBe("variable");
  });
});
