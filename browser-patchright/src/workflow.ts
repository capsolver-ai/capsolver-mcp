import { createRequire } from "node:module";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { getDefaultEnvironment, StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { BrowserManager } from "./browser/manager.js";

const { version: packageVersion } = createRequire(import.meta.url)("../package.json") as { version: string };

const prefix = "capsolver_";
const attach = "capsolver_browser_attach";

function workflowEnvironment(): Record<string, string> {
  const names = ["CAPSOLVER_STATE_DIR", "CAPSOLVER_OFFLINE", "PYTHONPATH", "PLAYWRIGHT_BROWSERS_PATH"];
  const env = getDefaultEnvironment();
  for (const name of names) {
    const value = process.env[name];
    if (value !== undefined) env[name] = value;
  }
  return env;
}

export class WorkflowBridge {
  private pending?: Promise<Client>;

  constructor(private readonly python: string, private readonly browser: BrowserManager) {}

  private client(): Promise<Client> {
    this.pending ??= this.connect().catch((error: unknown) => {
      this.pending = undefined;
      throw error;
    });
    return this.pending;
  }

  private async connect(): Promise<Client> {
    const client = new Client({ name: "capsolver-patchright-workflow", version: packageVersion });
    const transport = new StdioClientTransport({
      command: this.python,
      args: ["-m", "capsolver_mcp.browser_server"],
      env: workflowEnvironment(),
    });
    try {
      await client.connect(transport);
      return client;
    } catch (error) {
      await transport.close().catch(() => undefined);
      throw error;
    }
  }

  async tools() {
    const { tools } = await (await this.client()).listTools();
    return tools.map((tool) => {
      if (tool.name === "browser_open") {
        return {
          ...tool,
          name: attach,
          description: "Attach the CapSolver workflow to the active Chromium tab. Attach before navigating to capture the original responses.",
          inputSchema: {
            type: "object" as const,
            properties: {
              response_capture: { type: "object" },
            },
            additionalProperties: false,
          },
        };
      }
      return { ...tool, name: prefix + tool.name };
    });
  }

  async call(name: string, args: Record<string, unknown>) {
    const client = await this.client();
    if (name === attach) {
      if (Object.keys(args).some((key) => key !== "response_capture")) {
        throw new Error(`${attach} accepts only response_capture.`);
      }
      const target = await this.browser.workflowTarget();
      return await client.callTool({ name: "browser_open", arguments: {
        ...target, response_capture: args.response_capture,
      } });
    }
    const native = name.slice(prefix.length);
    if (native === "browser_open") throw new Error(`Use ${attach} for the active Patchright tab.`);
    return await client.callTool({ name: native, arguments: args });
  }

  async close(): Promise<void> {
    const client = this.pending;
    this.pending = undefined;
    if (client) await client.then((value) => value.close()).catch(() => undefined);
  }
}
