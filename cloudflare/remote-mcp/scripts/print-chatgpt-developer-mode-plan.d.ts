export interface ChatGptDeveloperModePlan {
  connector_name: string;
  connector_mode: string;
  worker_base_url: string;
  mcp_url: string;
  health_url: string;
  origin_base_url: string;
  worker_auth_mode: "worker-api-token" | "origin-only";
  recommended_worker_auth_mode: "origin-only";
  required_worker_secrets: string[];
  optional_worker_secrets: string[];
  recommendation: string;
  chatgpt_steps: string[];
  official_docs: {
    connect_from_chatgpt: string;
    auth: string;
    developer_mode: string;
  };
}

export function buildPlan(
  env?: Record<string, string | undefined>,
): ChatGptDeveloperModePlan;
