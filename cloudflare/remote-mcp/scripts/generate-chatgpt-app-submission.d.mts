export type SubmissionAppInfo = {
  display_name: string;
  subtitle: string;
  description: string;
  category: string;
};

export type SubmissionToolDetails = Record<
  string,
  {
    annotations: {
      readOnlyHint: boolean;
      openWorldHint: boolean;
      destructiveHint: boolean;
    };
    justifications: {
      read_only_justification: string;
      open_world_justification: string;
      destructive_justification: string;
    };
  }
>;

export type SubmissionTestCase = {
  description: string;
  user_prompt: string;
  file_attachment_urls: string[] | null;
  tools_triggered: string | null;
  expected_output: string;
  expected_output_url: string | null;
};

export type SubmissionPayload = {
  $schema: string;
  schema_version: number;
  app_info: SubmissionAppInfo;
  tools: SubmissionToolDetails;
  test_cases: SubmissionTestCase[];
  negative_test_cases: SubmissionTestCase[];
};

export function buildSubmissionPayload(): SubmissionPayload;
export function formatSubmissionPayload(payload: SubmissionPayload): string;
export function readExistingSubmission(): Promise<string>;
export function writeSubmissionFile(): Promise<string>;
export function verifySubmissionFile(): Promise<{
  expected: string;
  actual: string;
  matches: boolean;
}>;
