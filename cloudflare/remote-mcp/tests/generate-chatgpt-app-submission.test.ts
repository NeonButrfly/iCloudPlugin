import { describe, expect, it } from "vitest";

import {
  buildSubmissionPayload,
  formatSubmissionPayload,
} from "../scripts/generate-chatgpt-app-submission.mjs";

describe("generate-chatgpt-app-submission", () => {
  it("builds a submission payload for the current remote MCP surface", () => {
    const payload = buildSubmissionPayload();

    expect(payload.schema_version).toBe(1);
    expect(payload.app_info.display_name).toBe("iCloudPlugin Remote MCP");
    expect(Object.keys(payload.tools)).toEqual([
      "search_icloud_files",
      "search_icloud_notes_and_files",
      "get_icloud_system_status",
      "get_icloud_file",
      "get_icloud_file_excerpt",
      "get_icloud_note",
      "get_icloud_source_reference",
      "get_icloud_file_bundle",
      "refresh_icloud_index",
    ]);
    expect(payload.test_cases.length).toBeGreaterThanOrEqual(5);
    expect(payload.negative_test_cases.length).toBeGreaterThanOrEqual(3);
  });

  it("formats the submission payload as stable pretty JSON", () => {
    const formatted = formatSubmissionPayload(buildSubmissionPayload());

    expect(formatted.endsWith("\n")).toBe(true);
    expect(formatted).toContain('"display_name": "iCloudPlugin Remote MCP"');
    expect(formatted).toContain('"refresh_icloud_index"');
  });
});
