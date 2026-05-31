export const DEFAULT_REPO: string;
export const SECRET_MAPPINGS: Array<{
  sourceName: string;
  targetName: string;
  required: boolean;
  kind: "secret" | "variable";
}>;

export type BootstrapOptions = {
  repo: string;
  secretsFile: string;
  publicBaseUrl: string;
  apply: boolean;
  json: boolean;
};

export type BootstrapPlanEntry = {
  source_name: string;
  target_name: string;
  kind: "secret" | "variable";
  required: boolean;
  present: boolean;
  value_length: number;
};

export type BootstrapPlan = {
  repo: string;
  secrets_file: string | null;
  apply: boolean;
  entries: BootstrapPlanEntry[];
  missing_required: string[];
  can_apply: boolean;
};

export function parseArgs(argv: string[]): BootstrapOptions;
export function resolveBootstrapPlan(
  options: BootstrapOptions,
  env?: Record<string, string | undefined>,
): BootstrapPlan;
