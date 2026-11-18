import { handleExtension } from "./capsolver-extensions.js";
import { readFile, writeFile } from "node:fs/promises";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import type { Dialog, Locator, Page } from "patchright";
import type { BrowserManager } from "../browser/manager.js";
import { humanClick, humanType } from "../util/human.js";
import { redactDataUrls } from "../util/redact.js";
import {
  apiRequestSchema,
  closePageSchema,
  cookieDeleteSchema,
  cookieGetSchema,
  cookieListSchema,
  cookieSetSchema,
  dialogSchema,
  dragDropSchema,
  evaluateSchema,
  fileUploadSchema,
  fillFormSchema,
  fillSchema,
  findSchema,
  hideHighlightSchema,
  highlightSchema,
  iframeClickSchema,
  iframeFillSchema,
  navigateSchema,
  networkRequestSchema,
  networkRequestsSchema,
  networkStateSchema,
  newPageSchema,
  pageIdSchema,
  passkeyCreateSchema,
  passkeyDeleteSchema,
  passkeyListSchema,
  pressSchema,
  resizeSchema,
  routeBlockSchema,
  routeMockSchema,
  runCodeSchema,
  savePdfSchema,
  screenshotSchema,
  selectOptionSchema,
  snapshotSchema,
  startSchema,
  storageKeyDeleteSchema,
  storageKeyGetSchema,
  storageKeySetSchema,
  storageLoadSchema,
  storageSaveSchema,
  targetSchema,
  typeSchema,
  videoSaveSchema,
  visibleHtmlSchema,
  visibleTextSchema,
  waitForSchema,
} from "./schemas.js";

type ToolResult = CallToolResult;

function truncate(value: string, max?: number): { text: string; truncated: boolean; length: number } {
  const limit = max ?? 100_000;
  if (value.length <= limit) return { text: value, truncated: false, length: value.length };
  return { text: value.slice(0, limit), truncated: true, length: value.length };
}

function text(value: unknown): ToolResult {
  return {
    content: [
      {
        type: "text",
        text: typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "undefined",
      },
    ],
  };
}

function image(data: Buffer): ToolResult {
  return {
    content: [{ type: "image", data: data.toString("base64"), mimeType: "image/png" }],
  };
}

function safePasskey<T extends { privateKey: string }>(credential: T, includePrivateKey = false) {
  if (includePrivateKey) return credential;
  const { privateKey: _privateKey, ...safe } = credential;
  return { ...safe, hasPrivateKey: true };
}

// CDP Page.printToPDF takes paper dimensions in inches.
const PDF_PAPER: Record<string, { width: number; height: number }> = {
  Letter: { width: 8.5, height: 11 },
  Legal: { width: 8.5, height: 14 },
  Tabloid: { width: 11, height: 17 },
  A3: { width: 11.69, height: 16.54 },
  A4: { width: 8.27, height: 11.69 },
  A5: { width: 5.83, height: 8.27 },
};

// Distill an aria snapshot to cut token usage: drop verbose /url lines by
// default, redact data: URLs, and collapse redundant blank lines. Refs are
// preserved so downstream tools keep working.
function distillSnapshot(snapshot: string, opts: { includeUrls?: boolean } = {}): string {
  const lines = snapshot.split("\n");
  const out: string[] = [];
  let blank = false;
  for (const raw of lines) {
    if (!opts.includeUrls && /^\s*- \/url:/.test(raw)) continue;
    const line = redactDataUrls(raw);
    if (line.trim() === "") {
      if (blank) continue;
      blank = true;
    } else {
      blank = false;
    }
    out.push(line);
  }
  return out.join("\n").trim();
}

function locatorFor(page: Page, target: { selector?: string; ref?: string; frameSelector?: string }): Locator {
  const root = target.frameSelector ? page.frameLocator(target.frameSelector) : page;
  if (target.ref) return root.locator(`aria-ref=${target.ref}`);
  if (target.selector) return root.locator(target.selector);
  throw new Error("Missing selector or ref");
}


async function collectFingerprint(page: Page): Promise<unknown> {
  const client = await page.context().newCDPSession(page);
  const uaData = await client.send("Browser.getVersion").catch(() => undefined);
  await client.detach().catch(() => undefined);

  const data = await page.evaluate(() => {
    const glCanvas = document.createElement("canvas");
    const gl = (glCanvas.getContext("webgl") || glCanvas.getContext("experimental-webgl")) as WebGLRenderingContext | null;
    let webgl: { vendor?: string | null; renderer?: string | null } | undefined;
    if (gl) {
      const dbg = gl.getExtension("WEBGL_debug_renderer_info");
      webgl = {
        vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
        renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
      };
    }

    return {
      url: location.href,
      userAgent: navigator.userAgent,
      webdriver: navigator.webdriver,
      languages: navigator.languages,
      language: navigator.language,
      platform: navigator.platform,
      hardwareConcurrency: navigator.hardwareConcurrency,
      deviceMemory: (navigator as Navigator & { deviceMemory?: number }).deviceMemory,
      maxTouchPoints: navigator.maxTouchPoints,
      cookieEnabled: navigator.cookieEnabled,
      pluginsLength: navigator.plugins?.length,
      mimeTypesLength: navigator.mimeTypes?.length,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      screen: {
        width: screen.width,
        height: screen.height,
        availWidth: screen.availWidth,
        availHeight: screen.availHeight,
        colorDepth: screen.colorDepth,
        pixelDepth: screen.pixelDepth,
      },
      viewport: { width: innerWidth, height: innerHeight, devicePixelRatio },
      chromeRuntime: !!(globalThis as typeof globalThis & { chrome?: unknown }).chrome,
      permissionsQuery: !!navigator.permissions?.query,
      webgl,
    };
  });

  const warnings: string[] = [];
  if (data.webdriver) warnings.push("navigator.webdriver is truthy");
  if (/HeadlessChrome/i.test(data.userAgent)) warnings.push("User-Agent contains HeadlessChrome");
  if (!data.languages?.length) warnings.push("navigator.languages is empty");
  if (!data.pluginsLength) warnings.push("navigator.plugins is empty");
  if (data.viewport.width === 0 || data.viewport.height === 0) warnings.push("Viewport size is zero");

  return { ...data, browserVersion: uaData, warnings };
}

export async function handleTool(manager: BrowserManager, name: string, args: unknown): Promise<ToolResult> {
  const extension = await handleExtension(manager, name, args);
  if (extension) return extension;
  switch (name) {
    case "browser_start": {
      const parsed = startSchema.parse(args ?? {});
      // Normalize recordVideo: true -> {} (defaults), false -> undefined, object -> object.
      const { recordVideo, ...rest } = parsed;
      const normalized = {
        ...rest,
        ...(recordVideo === true ? { recordVideo: {} } : recordVideo && typeof recordVideo === "object" ? { recordVideo } : {}),
      };
      const page = await manager.start(normalized);
      return text({ ok: true, url: page.url(), status: await manager.status() });
    }
    case "browser_status": {
      return text(await manager.status());
    }
    case "browser_navigate": {
      const parsed = navigateSchema.parse(args);
      const page = await manager.getPage();
      const response = await page.goto(parsed.url, {
        waitUntil: parsed.waitUntil ?? "domcontentloaded",
        timeout: parsed.timeout ?? 30_000,
      });
      const status = response?.status();
      const failed = status !== undefined && status >= 400;
      return text({
        ok: !failed,
        url: page.url(),
        title: await page.title().catch(() => undefined),
        status,
        statusText: response?.statusText(),
        ...(failed ? { warning: `Navigation returned HTTP ${status}` } : {}),
      });
    }
    case "browser_new_page": {
      const parsed = newPageSchema.parse(args ?? {});
      return text(await manager.newPage(parsed.url));
    }
    case "browser_pages": {
      return text(await manager.listPages());
    }
    case "browser_switch_page": {
      const parsed = pageIdSchema.parse(args);
      return text(await manager.switchPage(parsed.pageId));
    }
    case "browser_close_page": {
      const parsed = closePageSchema.parse(args ?? {});
      return text(await manager.closePage(parsed.pageId));
    }
    case "browser_snapshot": {
      const parsed = snapshotSchema.parse(args ?? {});
      const page = await manager.getPage();
      const raw = await page.ariaSnapshot({ mode: "ai", timeout: 5_000 });
      const distilled = distillSnapshot(raw, { includeUrls: parsed.includeUrls });
      const out = truncate(distilled, parsed.maxLength);
      return text({
        url: page.url(),
        title: await page.title().catch(() => undefined),
        snapshot: out.text,
        truncated: out.truncated,
        length: out.length,
      });
    }
    case "browser_find": {
      const parsed = findSchema.parse(args);
      const page = await manager.getPage();
      const raw = await page.ariaSnapshot({ mode: "ai", timeout: 5_000 });
      const lines = distillSnapshot(raw).split("\n");
      const ctx = parsed.context ?? 2;
      const maxMatches = parsed.maxMatches ?? 20;
      const flags = parsed.ignoreCase === false ? "" : "i";
      let matcher: (line: string) => boolean;
      if (parsed.regex) {
        let re: RegExp;
        try {
          re = new RegExp(parsed.query, flags);
        } catch (e) {
          return text({ ok: false, error: `Invalid regex: ${e instanceof Error ? e.message : String(e)}` });
        }
        matcher = (line) => re.test(line);
      } else {
        const needle = flags ? parsed.query.toLowerCase() : parsed.query;
        matcher = (line) => (flags ? line.toLowerCase() : line).includes(needle);
      }
      const refRe = /\[ref=([a-zA-Z0-9]+)\]/;
      const matches: { line: number; text: string; ref?: string; context: string[] }[] = [];
      for (let i = 0; i < lines.length && matches.length < maxMatches; i++) {
        if (!matcher(lines[i])) continue;
        const start = Math.max(0, i - ctx);
        const end = Math.min(lines.length, i + ctx + 1);
        matches.push({
          line: i + 1,
          text: lines[i].trim(),
          ref: lines[i].match(refRe)?.[1],
          context: lines.slice(start, end),
        });
      }
      return text({ url: page.url(), query: parsed.query, total: matches.length, matches });
    }
    case "browser_take_screenshot": {
      const parsed = screenshotSchema.parse(args ?? {});
      const page = await manager.getPage();
      const shot = await page.screenshot({
        path: parsed.path,
        fullPage: parsed.fullPage ?? true,
        ...(parsed.scale ? { scale: parsed.scale } : {}),
      });
      if (parsed.path) return text({ ok: true, path: parsed.path });
      return image(shot);
    }
    case "browser_click": {
      const parsed = targetSchema.parse(args);
      const page = await manager.getPage();
      await humanClick(page, locatorFor(page, parsed), { timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_fill": {
      const parsed = fillSchema.parse(args);
      const page = await manager.getPage();
      await locatorFor(page, parsed).fill(parsed.text, { timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_type": {
      const parsed = typeSchema.parse(args);
      const page = await manager.getPage();
      const result = await humanType(page, locatorFor(page, parsed), parsed.text, {
        verify: parsed.verify,
        timeout: parsed.timeout ?? 30_000,
      });
      return text({ ok: true, verified: result.verified });
    }
    case "browser_hover": {
      const parsed = targetSchema.parse(args);
      const page = await manager.getPage();
      await locatorFor(page, parsed).hover({ timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_press_key": {
      const parsed = pressSchema.parse(args);
      const page = await manager.getPage();
      if (parsed.selector || parsed.ref) await locatorFor(page, parsed).press(parsed.key, { timeout: parsed.timeout ?? 30_000 });
      else await page.keyboard.press(parsed.key);
      return text({ ok: true });
    }
    case "browser_wait_for": {
      const parsed = waitForSchema.parse(args ?? {});
      const page = await manager.getPage();
      if (parsed.selector || parsed.ref) {
        await locatorFor(page, parsed).waitFor({ state: parsed.state ?? "visible", timeout: parsed.timeout ?? 30_000 });
      } else {
        await page.waitForTimeout(parsed.timeout ?? 1_000);
      }
      return text({ ok: true });
    }
    case "browser_evaluate": {
      const parsed = evaluateSchema.parse(args);
      const page = await manager.getPage();
      const code = parsed.function ?? parsed.script;
      if (code) {
        const result = await page.evaluate((script: string) => Function(`"use strict"; return (${script})`)(), code);
        return text(result);
      }
      if (parsed.expression) {
        const result = await page.evaluate(new Function(`return (${parsed.expression})`) as any);
        return text(result);
      }
      return text({ ok: false, error: "Provide function, expression, or script" });
    }
    case "browser_fingerprint_check": {
      const page = await manager.getPage();
      return text(await collectFingerprint(page));
    }
    case "browser_navigate_back": {
      const page = await manager.getPage();
      await page.goBack({ timeout: 10_000 }).catch(() => undefined);
      return text({ ok: true, url: page.url(), title: await page.title().catch(() => undefined) });
    }
    case "browser_select_option": {
      const parsed = selectOptionSchema.parse(args);
      const page = await manager.getPage();
      await locatorFor(page, parsed).selectOption(parsed.values, { timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_handle_dialog": {
      const parsed = dialogSchema.parse(args);
      const page = await manager.getPage();
      const handle = async (dialog: Dialog) => {
        const result = {
          type: dialog.type(),
          message: dialog.message(),
          defaultValue: dialog.defaultValue(),
          accepted: parsed.accept,
        };
        if (parsed.accept) await dialog.accept(parsed.promptText);
        else await dialog.dismiss();
        return result;
      };

      if (parsed.wait) {
        const dialog = await page.waitForEvent("dialog", { timeout: parsed.timeout ?? 30_000 });
        return text({ ok: true, dialog: await handle(dialog) });
      }

      page.once("dialog", (dialog) => {
        handle(dialog).catch(() => undefined);
      });
      return text({ ok: true, armed: true });
    }
    case "browser_file_upload": {
      const parsed = fileUploadSchema.parse(args);
      const page = await manager.getPage();
      await locatorFor(page, parsed).setInputFiles(parsed.paths, { timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_network_requests": {
      const parsed = networkRequestsSchema.parse(args ?? {});
      return text(manager.getNetworkRequests(parsed.activeOnly));
    }
    case "browser_network_request": {
      const parsed = networkRequestSchema.parse(args);
      const req =
        parsed.id !== undefined
          ? manager.getNetworkRequestById(parsed.id)
          : parsed.index !== undefined
            ? manager.getNetworkRequestByIndex(parsed.index)
            : undefined;
      if (!req) {
        return text({
          ok: false,
          error: parsed.id !== undefined ? `No request with id ${parsed.id}` : `No request at index ${parsed.index}`,
        });
      }
      return text(req);
    }
    case "browser_console_messages": {
      return text(manager.getConsoleMessages());
    }
    case "browser_resize": {
      const parsed = resizeSchema.parse(args);
      const page = await manager.getPage();
      await page.setViewportSize({ width: parsed.width, height: parsed.height });
      return text({ ok: true, width: parsed.width, height: parsed.height });
    }
    case "browser_drag": {
      const parsed = dragDropSchema.parse(args);
      const page = await manager.getPage();
      const src = locatorFor(page, parsed.source);
      const dst = locatorFor(page, parsed.target);
      await src.dragTo(dst, { timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_fill_form": {
      const parsed = fillFormSchema.parse(args);
      const page = await manager.getPage();
      const results: { name?: string; ok: boolean; error?: string }[] = [];
      for (const field of parsed.fields) {
        try {
          if (!field.selector && !field.ref) { results.push({ name: field.name, ok: false, error: "Missing selector or ref" }); continue; }
          await locatorFor(page, field).fill(field.value, { timeout: parsed.timeout ?? 30_000 });
          results.push({ name: field.name, ok: true });
        } catch (e: any) {
          results.push({ name: field.name, ok: false, error: e?.message ?? String(e) });
        }
      }
      return text({ ok: results.every(r => r.ok), fields: results });
    }
    case "browser_run_code_unsafe": {
      const parsed = runCodeSchema.parse(args);
      const page = await manager.getPage();
      const result = await page.evaluate(
        (opts: { script: string; args?: unknown[] }) => Function("args", opts.script)(opts.args),
        { script: parsed.script, args: parsed.args },
      );
      return text(result);
    }
    case "browser_network_state_set": {
      const parsed = networkStateSchema.parse(args);
      const page = await manager.getPage();
      await page.context().setOffline(parsed.offline);
      return text({ ok: true, offline: parsed.offline });
    }
    case "browser_api_request": {
      const parsed = apiRequestSchema.parse(args);
      const page = await manager.getPage();
      // context.request shares cookies/storage with the browser session,
      // so authenticated API calls work without re-login.
      const res = await page.context().request.fetch(parsed.url, {
        method: parsed.method ?? "GET",
        ...(parsed.headers ? { headers: parsed.headers } : {}),
        ...(parsed.data !== undefined ? { data: parsed.data } : {}),
        timeout: parsed.timeout ?? 30_000,
      });
      const body = truncate(await res.text(), parsed.maxBytes);
      return text({
        ok: res.ok(),
        status: res.status(),
        statusText: res.statusText(),
        url: res.url(),
        headers: res.headers(),
        body: body.text,
        truncated: body.truncated,
        length: body.length,
      });
    }
    case "browser_get_visible_text": {
      const parsed = visibleTextSchema.parse(args ?? {});
      const page = await manager.getPage();
      const raw = await page.evaluate(() => document.body?.innerText ?? "");
      const out = truncate(raw, parsed.maxLength);
      return text({ url: page.url(), text: out.text, truncated: out.truncated, length: out.length });
    }
    case "browser_get_visible_html": {
      const parsed = visibleHtmlSchema.parse(args ?? {});
      const page = await manager.getPage();
      const raw = await page.evaluate(
        (opts: { selector: string | null; removeScripts: boolean }) => {
          const root = opts.selector ? document.querySelector(opts.selector) : document.documentElement;
          if (!root) return "";
          const clone = root.cloneNode(true) as Element;
          if (opts.removeScripts) clone.querySelectorAll("script,style,noscript,template,svg").forEach((n) => { n.remove(); });
          return clone.outerHTML ?? "";
        },
        { selector: parsed.selector ?? null, removeScripts: parsed.removeScripts ?? true },
      );
      const out = truncate(raw, parsed.maxLength);
      return text({ url: page.url(), html: out.text, truncated: out.truncated, length: out.length });
    }
    case "browser_iframe_click": {
      const parsed = iframeClickSchema.parse(args);
      const page = await manager.getPage();
      await page.frameLocator(parsed.frameSelector).locator(parsed.selector).click({ timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_iframe_fill": {
      const parsed = iframeFillSchema.parse(args);
      const page = await manager.getPage();
      await page.frameLocator(parsed.frameSelector).locator(parsed.selector).fill(parsed.value, { timeout: parsed.timeout ?? 30_000 });
      return text({ ok: true });
    }
    case "browser_route_block": {
      const parsed = routeBlockSchema.parse(args ?? {});
      return text({ ok: true, routes: await manager.addBlockRoute(parsed) });
    }
    case "browser_route_mock": {
      const parsed = routeMockSchema.parse(args);
      return text({ ok: true, routes: await manager.addMockRoute(parsed) });
    }
    case "browser_route_clear": {
      const cleared = await manager.clearRoutes();
      return text({ ok: true, cleared });
    }
    case "browser_storage_save": {
      const parsed = storageSaveSchema.parse(args ?? {});
      const page = await manager.getPage();
      const state = await page.context().storageState(parsed.path ? { path: parsed.path } : {});
      if (parsed.path) {
        return text({ ok: true, path: parsed.path, cookies: state.cookies.length, origins: state.origins.length });
      }
      return text(state);
    }
    case "browser_storage_load": {
      const parsed = storageLoadSchema.parse(args);
      const page = await manager.getPage();
      const ctx = page.context();
      const state = parsed.state ?? JSON.parse(await readFile(parsed.path!, "utf8"));
      if (state.cookies?.length) await ctx.addCookies(state.cookies);
      // Persistent contexts can't ingest storageState at launch, so restore
      // localStorage by visiting each origin and writing entries directly.
      let originsApplied = 0;
      for (const origin of state.origins ?? []) {
        if (!origin.localStorage?.length) continue;
        await page.goto(origin.origin, { waitUntil: "domcontentloaded", timeout: 30_000 }).catch(() => undefined);
        await page.evaluate((items: { name: string; value: string }[]) => {
          for (const item of items) localStorage.setItem(item.name, item.value);
        }, origin.localStorage);
        originsApplied++;
      }
      return text({ ok: true, cookies: state.cookies?.length ?? 0, origins: originsApplied });
    }
    case "browser_cookie_list": {
      const parsed = cookieListSchema.parse(args ?? {});
      const page = await manager.getPage();
      let cookies = await page.context().cookies();
      if (parsed.domain) cookies = cookies.filter((c) => c.domain.includes(parsed.domain!));
      if (parsed.path) cookies = cookies.filter((c) => c.path === parsed.path);
      return text({ ok: true, count: cookies.length, cookies });
    }
    case "browser_cookie_get": {
      const parsed = cookieGetSchema.parse(args);
      const page = await manager.getPage();
      const cookie = (await page.context().cookies()).find((c) => c.name === parsed.name) ?? null;
      return text({ ok: true, cookie });
    }
    case "browser_cookie_set": {
      const parsed = cookieSetSchema.parse(args);
      const page = await manager.getPage();
      const cookie: Record<string, unknown> = { name: parsed.name, value: parsed.value };
      if (parsed.url) cookie.url = parsed.url;
      if (parsed.domain) { cookie.domain = parsed.domain; cookie.path = parsed.path ?? "/"; }
      // Fall back to the active page's origin when neither url nor domain is given.
      if (!parsed.url && !parsed.domain) {
        const current = page.url();
        if (!current || current === "about:blank") {
          return text({ ok: false, error: "Provide url or domain (no active origin to infer from)." });
        }
        cookie.url = current;
      }
      if (parsed.expires !== undefined) cookie.expires = parsed.expires;
      if (parsed.httpOnly !== undefined) cookie.httpOnly = parsed.httpOnly;
      if (parsed.secure !== undefined) cookie.secure = parsed.secure;
      if (parsed.sameSite !== undefined) cookie.sameSite = parsed.sameSite;
      await page.context().addCookies([cookie as any]);
      return text({ ok: true });
    }
    case "browser_cookie_delete": {
      const parsed = cookieDeleteSchema.parse(args);
      const page = await manager.getPage();
      await page.context().clearCookies({
        name: parsed.name,
        ...(parsed.domain ? { domain: parsed.domain } : {}),
        ...(parsed.path ? { path: parsed.path } : {}),
      });
      return text({ ok: true });
    }
    case "browser_cookie_clear": {
      const page = await manager.getPage();
      await page.context().clearCookies();
      return text({ ok: true });
    }
    case "browser_localstorage_list":
    case "browser_sessionstorage_list": {
      const store = name === "browser_localstorage_list" ? "localStorage" : "sessionStorage";
      const page = await manager.getPage();
      const items = await page.evaluate((s: string) => {
        const target = (window as any)[s] as Storage;
        const out: Record<string, string> = {};
        for (let i = 0; i < target.length; i++) {
          const k = target.key(i);
          if (k !== null) out[k] = target.getItem(k) ?? "";
        }
        return out;
      }, store);
      return text({ ok: true, origin: new URL(page.url()).origin, count: Object.keys(items).length, items });
    }
    case "browser_localstorage_get":
    case "browser_sessionstorage_get": {
      const store = name === "browser_localstorage_get" ? "localStorage" : "sessionStorage";
      const parsed = storageKeyGetSchema.parse(args);
      const page = await manager.getPage();
      const value = await page.evaluate(
        (o: { s: string; key: string }) => ((window as any)[o.s] as Storage).getItem(o.key),
        { s: store, key: parsed.key },
      );
      return text({ ok: true, key: parsed.key, value });
    }
    case "browser_localstorage_set":
    case "browser_sessionstorage_set": {
      const store = name === "browser_localstorage_set" ? "localStorage" : "sessionStorage";
      const parsed = storageKeySetSchema.parse(args);
      const page = await manager.getPage();
      await page.evaluate(
        (o: { s: string; key: string; value: string }) => ((window as any)[o.s] as Storage).setItem(o.key, o.value),
        { s: store, key: parsed.key, value: parsed.value },
      );
      return text({ ok: true, key: parsed.key });
    }
    case "browser_localstorage_delete":
    case "browser_sessionstorage_delete": {
      const store = name === "browser_localstorage_delete" ? "localStorage" : "sessionStorage";
      const parsed = storageKeyDeleteSchema.parse(args);
      const page = await manager.getPage();
      await page.evaluate(
        (o: { s: string; key: string }) => ((window as any)[o.s] as Storage).removeItem(o.key),
        { s: store, key: parsed.key },
      );
      return text({ ok: true, key: parsed.key });
    }
    case "browser_localstorage_clear":
    case "browser_sessionstorage_clear": {
      const store = name === "browser_localstorage_clear" ? "localStorage" : "sessionStorage";
      const page = await manager.getPage();
      await page.evaluate((s: string) => ((window as any)[s] as Storage).clear(), store);
      return text({ ok: true });
    }
    case "browser_passkey_install": {
      const page = await manager.getPage();
      await page.context().credentials.install();
      return text({ ok: true, installed: true });
    }
    case "browser_passkey_create": {
      const parsed = passkeyCreateSchema.parse(args);
      const page = await manager.getPage();
      const { rpId, includePrivateKey, ...material } = parsed;
      const credential = await page.context().credentials.create(rpId, material);
      return text({ ok: true, credential: safePasskey(credential, includePrivateKey) });
    }
    case "browser_passkey_list": {
      const parsed = passkeyListSchema.parse(args ?? {});
      const page = await manager.getPage();
      const { includePrivateKey, ...filter } = parsed;
      const credentials = await page.context().credentials.get(filter);
      return text({
        credentials: credentials.map((credential) => safePasskey(credential, includePrivateKey)),
      });
    }
    case "browser_passkey_delete": {
      const parsed = passkeyDeleteSchema.parse(args);
      const page = await manager.getPage();
      await page.context().credentials.delete(parsed.id);
      return text({ ok: true, deleted: parsed.id });
    }
    case "browser_video_save": {
      const parsed = videoSaveSchema.parse(args ?? {});
      if (parsed.path) return text(await manager.saveVideoAs(parsed.path));
      return text(await manager.videoInfo());
    }
    case "browser_highlight": {
      const parsed = highlightSchema.parse(args);
      const page = await manager.getPage();
      const key = parsed.label ?? parsed.selector ?? parsed.ref ?? "highlight";
      await locatorFor(page, parsed).evaluate(
        (el: Element, opts: { key: string; label?: string; style?: string }) => {
          let container = document.getElementById("__mcp_hl__");
          if (!container) {
            container = document.createElement("div");
            container.id = "__mcp_hl__";
            document.body.appendChild(container);
          }
          const r = el.getBoundingClientRect();
          const item = document.createElement("div");
          item.dataset.key = opts.key;
          item.style.cssText =
            `position:absolute;left:${r.left + window.scrollX}px;top:${r.top + window.scrollY}px;` +
            `width:${r.width}px;height:${r.height}px;pointer-events:none;z-index:2147483647;` +
            `outline:2px solid #ff3b30;box-shadow:0 0 0 2px rgba(255,59,48,.3);border-radius:2px;${opts.style ?? ""}`;
          if (opts.label) {
            const tag = document.createElement("div");
            tag.textContent = opts.label;
            tag.style.cssText =
              "position:absolute;top:-20px;left:0;background:#ff3b30;color:#fff;" +
              "font:11px/1.4 sans-serif;padding:1px 6px;border-radius:3px;white-space:nowrap;";
            item.appendChild(tag);
          }
          container.appendChild(item);
        },
        { key, label: parsed.label, style: parsed.style },
        { timeout: parsed.timeout ?? 30_000 } as any,
      );
      return text({ ok: true, key });
    }
    case "browser_hide_highlight": {
      const parsed = hideHighlightSchema.parse(args ?? {});
      const page = await manager.getPage();
      const key = parsed.label ?? parsed.selector ?? parsed.ref ?? null;
      const removed = await page.evaluate((k: string | null) => {
        const container = document.getElementById("__mcp_hl__");
        if (!container) return 0;
        if (!k) {
          const n = container.children.length;
          container.remove();
          return n;
        }
        let n = 0;
        container.querySelectorAll(`[data-key="${CSS.escape(k)}"]`).forEach((el) => { el.remove(); n++; });
        if (!container.children.length) container.remove();
        return n;
      }, key);
      return text({ ok: true, removed });
    }
    case "browser_save_pdf": {
      const parsed = savePdfSchema.parse(args ?? {});
      const page = await manager.getPage();
      // page.pdf() only works in headless Chromium, so drive CDP Page.printToPDF
      // directly — this works in headed/stealth mode too.
      const client = await page.context().newCDPSession(page);
      const paper = parsed.format ? PDF_PAPER[parsed.format] : undefined;
      try {
        const { data } = await client.send("Page.printToPDF", {
          landscape: parsed.landscape ?? false,
          printBackground: parsed.printBackground ?? true,
          scale: parsed.scale ?? 1,
          ...(paper ? { paperWidth: paper.width, paperHeight: paper.height } : {}),
        });
        const buf = Buffer.from(data, "base64");
        if (parsed.path) {
          await writeFile(parsed.path, buf);
          return text({ ok: true, path: parsed.path, bytes: buf.length });
        }
        return text({ ok: true, bytes: buf.length, pdfBase64: data });
      } finally {
        await client.detach().catch(() => undefined);
      }
    }
    case "browser_close": {
      const { videos, shutdown } = await manager.close();
      return text({ ok: true, ...(videos.length ? { videos } : {}), shutdown });
    }
    default:
      return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
  }
}
