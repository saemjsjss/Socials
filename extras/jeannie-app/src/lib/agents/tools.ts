// The core agent's tool set: live web search, reading a page, and the time
// tools. Only passed to models where supportsTools() is true (see llm.ts).

import type { SourceLink } from "../types";
import { createReadUrlTool } from "./read-url";
import { createSearchTool } from "./search-agent";
import { createConvertTimeTool, createCurrentTimeTool } from "./time-tools";

/** `onSources` collects pages the tools found or read, for the reply's sources footer. */
export function createCoreTools(onSources?: (sources: SourceLink[]) => void) {
  return {
    webSearch: createSearchTool(onSources),
    readUrl: createReadUrlTool(onSources),
    currentTime: createCurrentTimeTool(),
    convertTime: createConvertTimeTool(),
  };
}
