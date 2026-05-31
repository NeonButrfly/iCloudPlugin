export const APP_INFO = {
  display_name: "iCloudPlugin Remote MCP",
  subtitle: "Search private vault files",
  description:
    "iCloudPlugin Remote MCP helps users search a private indexed document vault, inspect generated notes and source metadata, review live system status, and trigger a bounded metadata refresh through ChatGPT.",
  category: "PRODUCTIVITY",
};

export const TOOL_SUBMISSION_DETAILS = {
  search_icloud_files: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only searches indexed private vault records and returns matching results without changing backend state.",
      open_world_justification:
        "Does not publish, send, or modify public internet content or third-party systems.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  search_icloud_notes_and_files: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only searches indexed records and hydrates bundled note and source metadata for the strongest matches without changing stored data.",
      open_world_justification:
        "Does not post or transmit changes to public internet state or external third-party systems.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  get_icloud_system_status: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only retrieves live service, queue, classifier, and vault status from the private backend.",
      open_world_justification:
        "Does not modify public internet state or write to third-party services.",
      destructive_justification:
        "Does not delete, overwrite, or trigger irreversible actions.",
    },
  },
  get_icloud_product_readiness: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only evaluates current repo and runtime readiness signals and reports which end-to-end criteria are met or blocked.",
      open_world_justification:
        "Does not publish or mutate public internet state or third-party systems.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  get_icloud_file: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only retrieves indexed metadata and extracted content for one private file record.",
      open_world_justification:
        "Does not publish or mutate external systems or public content.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  get_icloud_file_excerpt: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only retrieves file metadata and trims the returned content locally without changing backend state.",
      open_world_justification:
        "Does not modify public internet state or third-party services.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  get_icloud_note: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only retrieves generated note content and note metadata for one indexed private file.",
      open_world_justification:
        "Does not publish, send, or change external systems or public content.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  get_icloud_source_reference: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only returns canonical source paths, source links, and controlled download-handoff metadata for one file.",
      open_world_justification:
        "Does not publish or mutate public internet state or third-party systems.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  get_icloud_file_bundle: {
    annotations: {
      readOnlyHint: true,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Only retrieves file metadata, note content, and source reference data together for a single private file record.",
      open_world_justification:
        "Does not modify external systems or public internet state.",
      destructive_justification:
        "Does not delete, overwrite, or perform irreversible actions.",
    },
  },
  refresh_icloud_index: {
    annotations: {
      readOnlyHint: false,
      openWorldHint: false,
      destructiveHint: false,
    },
    justifications: {
      read_only_justification:
        "Queues a bounded private metadata refresh job on the backing service, so it changes internal backend state.",
      open_world_justification:
        "Only enqueues work on the private cloud-vault backend and does not publish or send changes to public internet systems.",
      destructive_justification:
        "Does not delete data or perform irreversible actions; it only requests a new internal refresh run.",
    },
  },
};

export const TEST_CASES = [
  {
    description: "Search private vault records for appeal-related files and notes.",
    user_prompt: "Search my private vault for appeal documents and show the strongest matches.",
    file_attachment_urls: null,
    tools_triggered: "search_icloud_notes_and_files",
    expected_output:
      "Returns bundled top matches with file metadata, generated note content, and source-reference metadata for relevant appeal items.",
    expected_output_url: null,
  },
  {
    description: "Inspect the live system status before troubleshooting indexing.",
    user_prompt: "Show me the current cloud-vault system status, including refresh progress and queue counts.",
    file_attachment_urls: null,
    tools_triggered: "get_icloud_system_status",
    expected_output:
      "Returns a consolidated status snapshot with service health, refresh progress, queue counts, and classifier readiness details.",
    expected_output_url: null,
  },
  {
    description: "Inspect overall product readiness before claiming the rollout is complete.",
    user_prompt: "Show me which cloud-vault product criteria are complete versus still blocked.",
    file_attachment_urls: null,
    tools_triggered: "get_icloud_product_readiness",
    expected_output:
      "Returns a consolidated readiness report with repo facts, live status summary, and explicit criteria marked met, blocked, or unknown.",
    expected_output_url: null,
  },
  {
    description: "Retrieve a generated note for a known indexed file.",
    user_prompt: "Open the generated note for file 8213 so I can review the current classification context.",
    file_attachment_urls: null,
    tools_triggered: "get_icloud_note",
    expected_output:
      "Returns note content and note metadata for the requested file id when a generated note is available.",
    expected_output_url: null,
  },
  {
    description: "Retrieve source reference metadata for a known indexed file.",
    user_prompt: "Show me the canonical source path and download handoff for file 23.",
    file_attachment_urls: null,
    tools_triggered: "get_icloud_source_reference",
    expected_output:
      "Returns canonical source metadata, source link information, and any controlled worker download URL for the requested file.",
    expected_output_url: null,
  },
  {
    description: "Queue a bounded metadata refresh on the private backend.",
    user_prompt: "Trigger a metadata refresh on the private cloud-vault index service.",
    file_attachment_urls: null,
    tools_triggered: "refresh_icloud_index",
    expected_output:
      "Acknowledges that a private refresh run was queued on the backing service.",
    expected_output_url: null,
  },
  {
    description: "Inspect one file with note and source context together.",
    user_prompt:
      "Get the full bundle for file 23 so I can review the file, note, and source reference together.",
    file_attachment_urls: null,
    tools_triggered: "get_icloud_file_bundle",
    expected_output:
      "Returns the indexed file payload, generated note payload, and source-reference payload together for the requested file id.",
    expected_output_url: null,
  },
];

export const NEGATIVE_TEST_CASES = [
  {
    description: "Do not trigger for general weather questions.",
    user_prompt: "What is the weather in Anchorage tomorrow?",
    file_attachment_urls: null,
    tools_triggered: null,
    expected_output:
      "The app should not be invoked because the request is unrelated to private vault search or status workflows.",
    expected_output_url: null,
  },
  {
    description: "Do not trigger for email-sending requests.",
    user_prompt: "Send this note to my insurance adjuster.",
    file_attachment_urls: null,
    tools_triggered: null,
    expected_output:
      "The app should not be invoked because it does not send email or publish messages to external systems.",
    expected_output_url: null,
  },
  {
    description: "Do not trigger for note-editing requests.",
    user_prompt: "Rewrite the contents of my Obsidian note to make it shorter.",
    file_attachment_urls: null,
    tools_triggered: null,
    expected_output:
      "The app should not be invoked because it retrieves note content but does not edit or overwrite vault notes.",
    expected_output_url: null,
  },
];
