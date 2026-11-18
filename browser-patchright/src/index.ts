#!/usr/bin/env node
import { randomUUID } from "node:crypto";
import type { Server as HttpServer } from "node:http";
import { createRequire } from "node:module";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { CallToolRequestSchema, isInitializeRequest, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import type { Request, Response } from "express";
import { BrowserManager, type StartOptions } from "./browser/manager.js";
import { handleTool } from "./tools/handlers.js";
import { tools } from "./tools/registry.js";
import { WorkflowBridge } from "./workflow.js";

const { version: packageVersion } = createRequire(import.meta.url)("../package.json") as {
  version: string;
};

type CliOptions = {
  host: string;
  port?: number;
  userDataDir?: string;
  headless?: boolean;
  outputMaxSize?: number;
  device?: string;
  mobile?: boolean;
  workflowPython?: string;
};

type ManagedServer = Server & { __manager: BrowserManager; __ownsManager: boolean; __workflow?: WorkflowBridge };

type ManagedTransport = SSEServerTransport | StreamableHTTPServerTransport;

function requestOwner(req: Request): string | undefined {
  const header = req.header("x-browser-owner");
  const query = typeof req.query.owner === "string" ? req.query.owner : undefined;
  const owner = header || query;
  if (!owner) return undefined;
  if (owner.length > 256) throw new Error("Invalid browser owner: too long");
  return owner;
}

function requiredRequestOwner(req: Request): string {
  const owner = requestOwner(req);
  if (!owner) throw new Error("browser owner is required in HTTP mode");
  return owner;
}

function parseCli(argv = process.argv.slice(2)): CliOptions {
  const options: CliOptions = { host: "127.0.0.1" };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const [flag, inlineValue] = arg.includes("=") ? arg.split(/=(.*)/s, 2) : [arg, undefined];
    const nextValue = () => inlineValue ?? argv[++index];

    switch (flag) {
      case "--host":
        options.host = nextValue();
        break;
      case "--port": {
        const value = Number(nextValue());
        if (!Number.isInteger(value) || value <= 0) throw new Error(`Invalid --port: ${String(value)}`);
        options.port = value;
        break;
      }
      case "--user-data-dir":
        options.userDataDir = nextValue();
        break;
      case "--headless":
        options.headless = true;
        break;
      case "--headed":
        options.headless = false;
        break;
      case "--output-max-size": {
        const value = Number(nextValue());
        if (!Number.isInteger(value) || value <= 0) throw new Error(`Invalid --output-max-size: ${String(value)}`);
        options.outputMaxSize = value;
        break;
      }
      case "--device":
        options.device = nextValue();
        break;
      case "--mobile":
        options.mobile = true;
        break;
      case "--workflow-python": {
        const command = nextValue();
        if (!command) throw new Error("--workflow-python requires a Python executable.");
        options.workflowPython = command;
        break;
      }
      case "--help":
      case "-h":
        printHelp();
        process.exit(0);
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }

  return options;
}

function printHelp(): void {
  console.log(`capsolver-patchright-mcp\n\nUsage:\n  capsolver-patchright-mcp                         # stdio MCP transport\n  capsolver-patchright-mcp --port 9100 [options]   # local HTTP MCP transport\n\nOptions:\n  --host <host>              Loopback HTTP host (default: 127.0.0.1)\n  --port <port>              Enable HTTP mode on this port\n  --user-data-dir <path>     Default persistent browser profile directory\n  --headless                 Start browser headless by default\n  --headed                   Start browser headed by default\n  --device <name>            Emulate a Playwright device\n  --mobile                   Enable mobile emulation\n  --output-max-size <bytes>  Cap each native tool response\n  --workflow-python <path>   Enable the same-tab CapSolver browser workflow\n`);
}

// Cap the total text size of a tool result. Oversized text is truncated with a
// marker so a single huge response can't blow up the client context.
function capResult(result: Awaited<ReturnType<typeof handleTool>>, maxSize?: number): typeof result {
  if (!maxSize || !result?.content) return result;
  for (const part of result.content) {
    if (part.type === "text" && typeof part.text === "string" && part.text.length > maxSize) {
      const omitted = part.text.length - maxSize;
      part.text = `${part.text.slice(0, maxSize)}\n\n[output truncated: ${omitted} chars omitted, over --output-max-size=${maxSize}]`;
    } else if (part.type === "image" && typeof part.data === "string" && part.data.length > maxSize) {
      // Drop oversized image payloads rather than truncate (a sliced base64 is
      // an unusable/corrupt image); replace with a text notice.
      const size = part.data.length;
      const notice = part as unknown as { type: string; text?: string; data?: unknown; mimeType?: unknown };
      notice.type = "text";
      notice.text = `[image omitted: ${size} chars base64 exceeds --output-max-size=${maxSize}]`;
      delete notice.data;
      delete notice.mimeType;
    }
  }
  return result;
}

function createServer(
  defaultStartOptions: StartOptions = {},
  sharedManager?: BrowserManager,
  outputMaxSize?: number,
  owner?: string,
  workflowPython?: string,
): ManagedServer {
  const server = new Server(
    {
      name: "capsolver-patchright-mcp",
      version: packageVersion,
    },
    {
      capabilities: {
        tools: {},
      },
    },
  ) as ManagedServer;

  const manager = sharedManager ?? new BrowserManager(defaultStartOptions, !!workflowPython);
  server.__manager = manager;
  server.__ownsManager = !sharedManager;

  const workflow = workflowPython ? new WorkflowBridge(workflowPython, manager) : undefined;
  server.__workflow = workflow;
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: workflow ? [...tools, ...await workflow.tools()] : tools,
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    try {
      const name = request.params.name;
      const args = request.params.arguments ?? {};
      if (workflow && name.startsWith("capsolver_")) {
        return await manager.runAsOwner(owner, () => workflow.call(name, args));
      }
      if (name === "browser_close") await workflow?.close();
      return capResult(
        await manager.runAsOwner(owner, () =>
          handleTool(manager, name, args),
        ),
        outputMaxSize,
      );
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
          },
        ],
        isError: true,
      };
    }
  });

  return server;
}

async function closeManagedServer(server: ManagedServer): Promise<void> {
  await server.__workflow?.close();
  if (server.__ownsManager) await server.__manager.close().catch(() => undefined);
  await server.close().catch(() => undefined);
}

async function startStdio(defaultStartOptions: StartOptions, outputMaxSize?: number, workflowPython?: string): Promise<void> {
  const server = createServer(defaultStartOptions, undefined, outputMaxSize, undefined, workflowPython);

  process.on("SIGINT", () => {
    void closeManagedServer(server).finally(() => process.exit(0));
  });
  process.on("SIGTERM", () => {
    void closeManagedServer(server).finally(() => process.exit(0));
  });
  process.stdin.once("end", () => {
    void closeManagedServer(server).finally(() => process.exit(0));
  });

  await server.connect(new StdioServerTransport());
}

async function startHttp(options: CliOptions & { port: number }, defaultStartOptions: StartOptions, outputMaxSize?: number): Promise<void> {
  const app = createMcpExpressApp();
  if (!["127.0.0.1", "::1", "localhost"].includes(options.host)) {
    throw new Error("The Patchright HTTP endpoint must bind to loopback.");
  }
  const sharedManager = new BrowserManager(defaultStartOptions, !!options.workflowPython);
  const transports: Record<string, ManagedTransport> = Object.create(null);
  const servers: Record<string, ManagedServer> = Object.create(null);

  app.get("/health", async (_req: Request, res: Response) => {
    res.json({ ok: true, name: "capsolver-patchright-mcp", transports: Object.keys(transports).length, browser: await sharedManager.status().catch(() => undefined) });
  });

  app.delete("/owners", async (req: Request, res: Response) => {
    try {
      const owner = requestOwner(req);
      if (!owner) {
        res.status(400).json({ ok: false, error: "owner is required" });
        return;
      }
      const closed = await sharedManager.closeOwnerPages(owner);
      res.json({ ok: true, owner, closed });
    } catch (error) {
      res.status(400).json({ ok: false, error: error instanceof Error ? error.message : String(error) });
    }
  });

  app.all("/mcp", async (req: Request, res: Response) => {
    try {
      const sessionId = req.headers["mcp-session-id"];
      const normalizedSessionId = Array.isArray(sessionId) ? sessionId[0] : typeof sessionId === "string" ? sessionId : undefined;
      let transport: StreamableHTTPServerTransport | undefined;

      if (normalizedSessionId && transports[normalizedSessionId]) {
        const existingTransport = transports[normalizedSessionId];
        if (!(existingTransport instanceof StreamableHTTPServerTransport)) {
          res.status(400).json({ jsonrpc: "2.0", error: { code: -32000, message: "Session uses a different transport protocol" }, id: null });
          return;
        }
        transport = existingTransport;
      } else if (!normalizedSessionId && req.method === "POST" && isInitializeRequest(req.body)) {
        let server: ManagedServer | undefined;
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (newSessionId: string) => {
            if (!transport || !server) return;
            transports[newSessionId] = transport;
            servers[newSessionId] = server;
          },
        });

        const owner = requestOwner(req);
        if (!owner) {
          res.status(400).json({ jsonrpc: "2.0", error: { code: -32600, message: "browser owner is required in HTTP mode" }, id: null });
          return;
        }
        server = createServer(defaultStartOptions, sharedManager, outputMaxSize, owner, options.workflowPython);
        transport.onclose = () => {
          const sid = transport?.sessionId;
          if (sid) {
            delete transports[sid];
            const managedServer = servers[sid];
            delete servers[sid];
            if (managedServer) void closeManagedServer(managedServer);
          }
        };
        await server.connect(transport);
      } else {
        res.status(400).json({ jsonrpc: "2.0", error: { code: -32000, message: "Bad Request: No valid session ID provided" }, id: null });
        return;
      }

      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      console.error("Error handling /mcp request:", error);
      if (!res.headersSent) {
        res.status(500).json({ jsonrpc: "2.0", error: { code: -32603, message: "Internal server error" }, id: null });
      }
    }
  });

  app.get("/sse", async (req: Request, res: Response) => {
    let owner: string;
    try {
      owner = requiredRequestOwner(req);
    } catch (error) {
      res.status(400).json({ error: error instanceof Error ? error.message : String(error) });
      return;
    }
    const transport = new SSEServerTransport("/messages", res);
    const server = createServer(defaultStartOptions, sharedManager, outputMaxSize, owner, options.workflowPython);
    transports[transport.sessionId] = transport;
    servers[transport.sessionId] = server;

    res.on("close", () => {
      const sid = transport.sessionId;
      delete transports[sid];
      delete servers[sid];
      void closeManagedServer(server);
    });

    await server.connect(transport);
  });

  app.post("/messages", async (req: Request, res: Response) => {
    const sessionId = req.query.sessionId;
    const normalizedSessionId = typeof sessionId === "string" ? sessionId : Array.isArray(sessionId) && typeof sessionId[0] === "string" ? sessionId[0] : undefined;
    const existingTransport = normalizedSessionId ? transports[normalizedSessionId] : undefined;

    if (!(existingTransport instanceof SSEServerTransport)) {
      res.status(400).send("No SSE transport found for sessionId");
      return;
    }

    await existingTransport.handlePostMessage(req, res, req.body);
  });

  const httpServer = await new Promise<HttpServer>((resolve, reject) => {
    const server = app.listen(options.port, options.host, () => resolve(server));
    server.on("error", reject);
  });

  const shutdown = () => {
    void (async () => {
      for (const [sessionId, transport] of Object.entries(transports)) {
        await transport.close().catch(() => undefined);
        delete transports[sessionId];
      }
      for (const [sessionId, server] of Object.entries(servers)) {
        await closeManagedServer(server);
        delete servers[sessionId];
      }
      await sharedManager.close().catch(() => undefined);
      await new Promise<void>((resolve) => httpServer.close(() => resolve()));
      process.exit(0);
    })();
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  console.error(`mcp-patchright listening on http://${options.host}:${options.port}`);
  console.error(`  SSE:        http://${options.host}:${options.port}/sse`);
  console.error(`  Streamable: http://${options.host}:${options.port}/mcp`);
}

process.umask(0o077);
const cliOptions = parseCli();
const defaultStartOptions: StartOptions = {
  ...(cliOptions.userDataDir ? { userDataDir: cliOptions.userDataDir } : {}),
  ...(cliOptions.headless !== undefined ? { headless: cliOptions.headless } : {}),
  ...(cliOptions.device ? { device: cliOptions.device } : {}),
  ...(cliOptions.mobile ? { mobile: cliOptions.mobile } : {}),
};

if (cliOptions.port !== undefined) {
  await startHttp({ ...cliOptions, port: cliOptions.port }, defaultStartOptions, cliOptions.outputMaxSize);
} else {
  await startStdio(defaultStartOptions, cliOptions.outputMaxSize, cliOptions.workflowPython);
}
