/** CapSolver extensions over the directly pinned mcp-patchright source.
 * Public tool names remain compatible with previous local installations.
 */
import { writeFile } from "node:fs/promises";
import type { CallToolResult, Tool } from "@modelcontextprotocol/sdk/types.js";
import type { Frame, Page } from "patchright";
import { z } from "zod";
import type { BrowserManager } from "../browser/manager.js";

const codeField = z.string().min(1).optional();
const execution = z.object({
  expression: codeField,
  function: codeField,
  script: codeField,
  world: z.enum(["isolated", "main"]).default("isolated"),
  frameSelector: codeField,
}).refine(value => value.expression || value.function || value.script, "Supply executable JavaScript.");
const exportRequest = z.object({
  expression: codeField,
  function: codeField,
  world: z.enum(["isolated", "main"]).default("isolated"),
  path: z.string().min(1),
  encoding: z.enum(["base64", "text"]).default("text"),
}).refine(value => value.expression || value.function, "Supply an expression or function.");
const initializer = z.object({ function: codeField, script: codeField })
  .refine(value => value.function || value.script, "Supply an initialization script.");
const statements = z.object({
  script: z.string().min(1),
  args: z.array(z.unknown()).optional(),
  world: z.enum(["isolated", "main"]).default("isolated"),
});

const worldProperty = { type: "string", enum: ["isolated", "main"], description: "Select isolated execution (default) or the page's main JavaScript world." };

export function extendBrowserTools(base: Tool[]): Tool[] {
  const expanded = base.map(tool => {
    if (tool.name !== "browser_evaluate" && tool.name !== "browser_run_code_unsafe") return tool;
    return {
      ...tool,
      description: `${tool.description} Supports world selection${tool.name === "browser_evaluate" ? " and an explicit iframe selector" : ""}.`,
      inputSchema: { ...tool.inputSchema, properties: {
        ...tool.inputSchema.properties,
        world: worldProperty,
        ...(tool.name === "browser_evaluate" ? { frameSelector: { type: "string", description: "CSS selector of the target iframe; unresolved selectors fail." } } : {}),
      } },
    };
  });
  return [...expanded, {
    name: "browser_add_init_script",
    description: "Install a function expression or statements before scripts on future navigations of the current page and its frames. Does not modify already-loaded content or other owners' pages.",
    inputSchema: { type: "object", properties: {
      function: { type: "string" }, script: { type: "string", description: "Compatibility alias." },
    } },
  }, {
    name: "browser_save_blob",
    description: "Evaluate a page expression or function and save its result locally without returning the payload through MCP. Supports UTF-8 text/JSON and base64-encoded bytes.",
    inputSchema: { type: "object", properties: {
      function: { type: "string" }, expression: { type: "string" }, world: worldProperty,
      path: { type: "string" }, encoding: { type: "string", enum: ["base64", "text"] },
    }, required: ["path"] },
  }];
}

function reply(value: unknown): CallToolResult {
  return { content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "undefined" }] };
}

type Code = { source: string; invoke: boolean; statementArgs?: unknown[]; statements?: boolean };
async function execute(target: Page | Frame, code: Code, world: "main" | "isolated"): Promise<unknown> {
  // Patchright's third argument selects the execution world. Keep this adapter
  // in one place so an upstream API change has a single integration boundary.
  const evaluate = target.evaluate.bind(target) as (
    callback: (input: Code) => unknown, input: Code, isolated: boolean,
  ) => Promise<unknown>;
  return evaluate(input => {
    if (input.statements) return new Function("args", input.source)(input.statementArgs);
    const value = new Function(`return (${input.source}\n);`)();
    return input.invoke && typeof value === "function" ? value() : value;
  }, code, world !== "main");
}

async function selectFrame(page: Page, selector?: string): Promise<Page | Frame> {
  if (!selector) return page;
  const element = await page.locator(selector).elementHandle();
  if (!element) throw new Error("frameSelector did not match an iframe.");
  try {
    const frame = await element.contentFrame();
    if (!frame) throw new Error("frameSelector matched a non-frame element.");
    return frame;
  } finally {
    await element.dispose();
  }
}

export async function handleExtension(manager: BrowserManager, name: string, args: unknown): Promise<CallToolResult | undefined> {
  if (name === "browser_evaluate") {
    const request = execution.parse(args);
    const target = await selectFrame(await manager.getPage(), request.frameSelector);
    return reply(await execute(target, {
      source: (request.function ?? request.script ?? request.expression)!,
      invoke: !!request.function,
    }, request.world));
  }
  if (name === "browser_run_code_unsafe") {
    const request = statements.parse(args);
    return reply(await execute(await manager.getPage(), {
      source: request.script, invoke: false, statements: true, statementArgs: request.args,
    }, request.world));
  }
  if (name === "browser_add_init_script") {
    const request = initializer.parse(args);
    const source = (request.function ?? request.script)!;
    let content: string;
    try {
      // Compile without running. Runtime errors must never trigger a second run.
      new Function(`return (${source}\n);`);
      content = `(() => { const init = (${source}\n); if (typeof init === "function") init(); })();`;
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      content = source;
    }
    await (await manager.getPage()).addInitScript({ content });
    return reply({ ok: true, note: "Installed for future navigations of this page." });
  }
  if (name === "browser_save_blob") {
    const request = exportRequest.parse(args);
    const value = await execute(await manager.getPage(), {
      source: (request.function ?? request.expression)!, invoke: !!request.function,
    }, request.world);
    if (value == null) return reply({ ok: false, error: "No value was produced; the destination was not changed." });
    let bytes: Buffer;
    if (request.encoding === "base64") {
      if (typeof value !== "string") return reply({ ok: false, error: "Base64 export requires a string result." });
      const encoded = value.startsWith("data:") ? value.slice(value.indexOf(",") + 1) : value;
      bytes = Buffer.from(encoded, "base64");
    } else {
      bytes = Buffer.from(typeof value === "string" ? value : JSON.stringify(value), "utf8");
    }
    await writeFile(request.path, bytes, { mode: 0o600 });
    return reply({ ok: true, path: request.path, bytes: bytes.length });
  }
  return undefined;
}
