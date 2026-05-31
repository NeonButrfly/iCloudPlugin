export const DEFAULT_MCP_ROUTE: string;
export const DEFAULT_HEALTH_ROUTE: string;
export const DEFAULT_EXPECTED_TOOLS: string[];

export type VerifyOptions = {
  mcpUrl: string;
  baseUrl: string;
  token: string;
  probeTool: string;
  probeArgsRaw: string;
  expectToolsCsv: string;
  headers: string[];
  skipHealth: boolean;
  json: boolean;
};

export type VerifyConfig = {
  mcpUrl: string;
  healthUrl: string;
  token: string;
  headers: Record<string, string>;
  probeTool: string;
  probeArgs: Record<string, unknown>;
  expectedTools: string[];
  skipHealth: boolean;
  json: boolean;
};

export function parseArgs(argv: string[]): VerifyOptions;
export function buildDerivedUrls(baseUrl: string): { mcpUrl: string; healthUrl: string };
export function parseJsonObject(rawValue: string, label: string): Record<string, unknown>;
export function buildAuthHeaders(token: string): Record<string, string>;
export function parseHeaderEntry(rawValue: string): { name: string; value: string };
export function parseHeadersJson(rawValue: string): Record<string, string>;
export function resolveExtraHeaders(
  options: VerifyOptions,
  env?: Record<string, string | undefined>,
): Record<string, string>;
export function summarizeProbeResult(result: {
  isError?: boolean;
  structuredContent?: unknown;
  content?: Array<Record<string, unknown> & { type?: string; text?: string }>;
}): {
  isError: boolean;
  structuredContent: unknown;
  contentPreview: string[];
};
export function resolveConfig(
  options: VerifyOptions,
  env?: Record<string, string | undefined>,
): VerifyConfig;
export function fetchHealthSummary(config: VerifyConfig): Promise<Record<string, unknown> | null>;
export function runVerification(
  config: VerifyConfig,
): Promise<Record<string, unknown>>;
