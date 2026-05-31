import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  APP_INFO,
  NEGATIVE_TEST_CASES,
  TEST_CASES,
  TOOL_SUBMISSION_DETAILS,
} from "./chatgpt-app-submission-content.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..");
const SUBMISSION_PATH = path.join(REPO_ROOT, "chatgpt-app-submission.json");

export function buildSubmissionPayload() {
  return {
    $schema: "https://developers.openai.com/apps-sdk/schemas/chatgpt-app-submission.v1.json",
    schema_version: 1,
    app_info: APP_INFO,
    tools: TOOL_SUBMISSION_DETAILS,
    test_cases: TEST_CASES,
    negative_test_cases: NEGATIVE_TEST_CASES,
  };
}

export function formatSubmissionPayload(payload) {
  return `${JSON.stringify(payload, null, 2)}\n`;
}

export async function readExistingSubmission() {
  return fs.readFile(SUBMISSION_PATH, "utf-8");
}

export async function writeSubmissionFile() {
  const formatted = formatSubmissionPayload(buildSubmissionPayload());
  await fs.writeFile(SUBMISSION_PATH, formatted, "utf-8");
  return formatted;
}

export async function verifySubmissionFile() {
  const expected = formatSubmissionPayload(buildSubmissionPayload());
  const actual = await readExistingSubmission();
  return {
    expected,
    actual,
    matches: actual === expected,
  };
}

function parseArgs(argv) {
  const args = {
    write: false,
    json: false,
  };

  for (const arg of argv) {
    if (arg === "--write") {
      args.write = true;
      continue;
    }
    if (arg === "--json") {
      args.json = true;
      continue;
    }
    if (arg === "--help") {
      args.help = true;
      continue;
    }
    throw new Error(`Unknown argument: ${arg}`);
  }

  return args;
}

function printUsage() {
  console.log(`Usage: node scripts/generate-chatgpt-app-submission.mjs [options]

Options:
  --write    Rewrite chatgpt-app-submission.json from structured source data
  --json     Print machine-readable summary output
  --help     Show this help text
`);
}

async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);

  if (args.help) {
    printUsage();
    return;
  }

  if (args.write) {
    const formatted = await writeSubmissionFile();
    if (args.json) {
      console.log(
        JSON.stringify(
          {
            wrote: true,
            path: SUBMISSION_PATH,
            bytes: Buffer.byteLength(formatted, "utf-8"),
          },
          null,
          2,
        ),
      );
      return;
    }
    console.log(`Wrote ${SUBMISSION_PATH}`);
    return;
  }

  const result = await verifySubmissionFile();
  if (args.json) {
    console.log(
      JSON.stringify(
        {
          matches: result.matches,
          path: SUBMISSION_PATH,
        },
        null,
        2,
      ),
    );
  } else if (result.matches) {
    console.log(`Verified ${SUBMISSION_PATH}`);
  } else {
    console.error(`Submission artifact drift detected in ${SUBMISSION_PATH}`);
  }

  if (!result.matches) {
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
