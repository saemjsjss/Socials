#!/usr/bin/env node
// Bulk-uploads markdown / JSON Lines notes to Jeannie's memory through /api/memory.
//
//   npm run memory:upload -- memory/profile.md --pin
//   npm run memory:upload -- memory/*.md memory/saemur-knowledge.jsonl
//
// Reads JEANNIE_URL (default http://localhost:3000) and JEANNIE_ACCESS_KEY from
// the environment or .env.local. --pin pins every file in this run (always in
// Jeannie's prompt); re-uploading a file name replaces the stored copy.

import { existsSync } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { basename } from "node:path";

if (existsSync(".env.local")) process.loadEnvFile(".env.local");

const args = process.argv.slice(2);
const pinned = args.includes("--pin");
const files = args.filter((a) => !a.startsWith("--"));
const baseUrl = (process.env.JEANNIE_URL || "http://localhost:3000").replace(/\/+$/, "");
const key = process.env.JEANNIE_ACCESS_KEY?.trim();

if (files.length === 0) {
  console.error("Usage: npm run memory:upload -- <file.md|file.jsonl>... [--pin]");
  process.exit(2);
}
if (!key) {
  console.error("Set JEANNIE_ACCESS_KEY (memory needs it) in the environment or .env.local.");
  process.exit(2);
}

let failed = 0;
for (const file of files) {
  try {
    const info = await stat(file);
    if (info.size > 1024 * 1024) throw new Error("larger than 1 MB");
    const content = await readFile(file, "utf8");
    const res = await fetch(`${baseUrl}/api/memory`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-jeannie-key": key },
      body: JSON.stringify({ name: basename(file), content, pinned }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(`${body.error ?? `HTTP ${res.status}`}${body.issues?.length ? ` (${body.issues.map((i) => `line ${i.line}: ${i.message}`).join("; ")})` : ""}`);
    const { chunks, issues } = body.document;
    console.log(`✓ ${file}: ${chunks} note${chunks === 1 ? "" : "s"}${pinned ? ", pinned" : ""}${issues.length ? `, ${issues.length} line(s) skipped` : ""}`);
  } catch (error) {
    failed++;
    console.error(`✗ ${file}: ${error instanceof Error ? error.message : error}`);
  }
}
process.exit(failed ? 1 : 0);
