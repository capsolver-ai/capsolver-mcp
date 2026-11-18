import { extendBrowserTools } from "./capsolver-extensions.js";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";

const targetProperties = {
  selector: { type: "string", description: "CSS selector. Provide exactly one of selector or ref." },
  ref: { type: "string", description: "aria-ref from browser_snapshot, for example e12. Provide exactly one of selector or ref." },
  frameSelector: { type: "string", description: "Optional CSS selector for an iframe. When set, selector/ref resolve inside that frame." },
  timeout: { type: "number" },
} as const;

const upstreamTools: Tool[] = [
  {
    name: "browser_start",
    description: "Start a browser session. Defaults to patchright chromium headed Chrome with a persistent profile.",
    inputSchema: {
      type: "object",
      properties: {
        browser: { type: "string", enum: ["chromium", "firefox", "webkit"] },
        headless: { type: "boolean" },
        width: { type: "number" },
        height: { type: "number" },
        userAgent: { type: "string" },
        userDataDir: { type: "string" },
        channel: { type: "string", enum: ["chrome", "chrome-beta", "chrome-dev", "chrome-canary", "msedge"] },
        locale: { type: "string" },
        timezoneId: { type: "string" },
        geolocation: {
          type: "object",
          description: "Spoof geolocation. Grants the geolocation permission automatically.",
          properties: {
            latitude: { type: "number" },
            longitude: { type: "number" },
            accuracy: { type: "number" },
          },
          required: ["latitude", "longitude"],
        },
        colorScheme: { type: "string", enum: ["light", "dark", "no-preference"] },
        device: { type: "string", description: "Emulate a device from the Playwright registry, e.g. \"iPhone 15\", \"Pixel 7\". Sets viewport, UA, scale factor, and touch." },
        mobile: { type: "boolean", description: "Enable mobile emulation (touch + mobile hints) without a full device descriptor." },
        cdpEndpoint: { type: "string", description: "Existing Chrome remote debugging endpoint, e.g. http://127.0.0.1:9222" },
        recordVideo: {
          description: "Record a video of the whole session. Pass true for defaults, or an object to customize. Saved as .webm; files finalize on browser_close. Not available over cdpEndpoint.",
          oneOf: [
            { type: "boolean" },
            {
              type: "object",
              properties: {
                dir: { type: "string", description: "Output directory. Defaults to ~/.maestro/stealth-playwright-mcp/videos." },
                width: { type: "number", description: "Video width. Defaults to viewport width." },
                height: { type: "number", description: "Video height. Defaults to viewport height." },
              },
            },
          ],
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "browser_status",
    description: "Return current browser status.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_navigate",
    description: "Navigate the active page to a URL.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string" },
        waitUntil: { type: "string", enum: ["load", "domcontentloaded", "networkidle", "commit"] },
        timeout: { type: "number" },
      },
      required: ["url"],
    },
  },

  {
    name: "browser_new_page",
    description: "Open a new page/tab and make it active. Optionally navigate to a URL.",
    inputSchema: {
      type: "object",
      properties: { url: { type: "string" } },
    },
  },
  {
    name: "browser_pages",
    description: "List open pages/tabs with ids, active state, URL, and title.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_switch_page",
    description: "Switch the active page/tab by pageId from browser_pages.",
    inputSchema: {
      type: "object",
      properties: { pageId: { type: "string" } },
      required: ["pageId"],
    },
  },
  {
    name: "browser_close_page",
    description: "Close a page/tab by pageId, or the active page if omitted.",
    inputSchema: {
      type: "object",
      properties: { pageId: { type: "string" } },
    },
  },
  {
    name: "browser_snapshot",
    description: "Return a distilled AI-oriented aria snapshot (verbose /url lines dropped and data: URLs collapsed to save tokens). Use [ref=eN] values with browser_click/fill/type/hover/press/wait_for.",
    inputSchema: {
      type: "object",
      properties: {
        maxLength: { type: "number", description: "Truncate snapshot to this many chars." },
        includeUrls: { type: "boolean", description: "Keep /url lines for links. Default false for token efficiency." },
      },
    },
  },
  {
    name: "browser_find",
    description: "Search the current page's aria snapshot for text or a regex. Returns matching nodes with their [ref] and a few lines of surrounding context — cheaper than a full browser_snapshot when you only need to locate an element.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Text substring, or a regex source when regex=true." },
        regex: { type: "boolean", description: "Treat query as a regular expression." },
        ignoreCase: { type: "boolean", description: "Case-insensitive match. Default true." },
        context: { type: "number", description: "Lines of surrounding context per match. Default 2." },
        maxMatches: { type: "number", description: "Max matches to return. Default 20." },
      },
      required: ["query"],
    },
  },
  {
    name: "browser_take_screenshot",
    description: "Take a screenshot. Returns base64 if path is omitted.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string" },
        fullPage: { type: "boolean" },
        scale: { type: "string", enum: ["css", "device"], description: "css = smaller, device-consistent CSS pixels; device = full device-pixel resolution." },
      },
    },
  },
  {
    name: "browser_click",
    description: "Click an element by CSS selector or aria ref from browser_snapshot.",
    inputSchema: {
      type: "object",
      properties: targetProperties,
    },
  },
  {
    name: "browser_fill",
    description: "Fill an input by CSS selector or aria ref from browser_snapshot.",
    inputSchema: {
      type: "object",
      properties: {
        ...targetProperties,
        text: { type: "string" },
      },
      required: ["text"],
    },
  },
  {
    name: "browser_type",
    description:
      "Type text into an element (CSS selector or aria ref) with human-like input: real per-key events, real Shift keyDown/up for capitals & symbols, variable dwell and inter-key gaps. Verifies the result against the request for input/textarea and errors on mismatch.",
    inputSchema: {
      type: "object",
      properties: {
        ...targetProperties,
        text: { type: "string" },
        verify: { type: "boolean", description: "Verify typed value matches request (default true) for input/textarea." },
        delay: { type: "number", description: "Deprecated/ignored; timing is randomized." },
      },
      required: ["text"],
    },
  },
  {
    name: "browser_hover",
    description: "Hover an element by CSS selector or aria ref from browser_snapshot.",
    inputSchema: {
      type: "object",
      properties: targetProperties,
    },
  },
  {
    name: "browser_press_key",
    description: "Press a keyboard key, optionally focused on a selector or aria ref first.",
    inputSchema: {
      type: "object",
      properties: {
        key: { type: "string" },
        selector: { type: "string" },
        ref: { type: "string" },
        frameSelector: { type: "string", description: "Optional iframe CSS selector; selector/ref resolve inside it." },
        timeout: { type: "number" },
      },
      required: ["key"],
    },
  },
  {
    name: "browser_wait_for",
    description: "Wait for time or for selector/ref state. If no selector/ref, waits timeout milliseconds.",
    inputSchema: {
      type: "object",
      properties: {
        selector: { type: "string" },
        ref: { type: "string" },
        frameSelector: { type: "string", description: "Optional iframe CSS selector; selector/ref resolve inside it." },
        state: { type: "string", enum: ["attached", "detached", "visible", "hidden"] },
        timeout: { type: "number" },
      },
    },
  },
  {
    name: "browser_evaluate",
    description: "Evaluate JavaScript in the active page. Pass 'function' for a function body, 'expression' for a plain expression, or 'script' (deprecated).",
    inputSchema: {
      type: "object",
      properties: {
        function: { type: "string" },
        expression: { type: "string" },
        script: { type: "string" },
      },
    },
  },
  {
    name: "browser_fingerprint_check",
    description: "Collect browser fingerprint diagnostics from the active page.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_navigate_back",
    description: "Navigate back in browser history.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_select_option",
    description: "Select options from a <select> element by CSS selector or aria ref.",
    inputSchema: {
      type: "object",
      properties: {
        ...targetProperties,
        values: { type: "array", items: { type: "string" }, description: "Option values or labels to select." },
      },
      required: ["values"],
    },
  },
  {
    name: "browser_handle_dialog",
    description: "Accept or dismiss a JavaScript dialog (alert / confirm / prompt).",
    inputSchema: {
      type: "object",
      properties: {
        accept: { type: "boolean", description: "true = accept, false = dismiss" },
        promptText: { type: "string", description: "Text to enter for prompt dialogs" },
        wait: { type: "boolean", description: "When true, wait for and handle the next dialog before returning. Default false arms a one-shot handler for the next action." },
        timeout: { type: "number", description: "Milliseconds to wait when wait=true" },
      },
      required: ["accept"],
    },
  },
  {
    name: "browser_file_upload",
    description: "Upload files to a <input type=file> by CSS selector or aria ref.",
    inputSchema: {
      type: "object",
      properties: {
        ...targetProperties,
        paths: { type: "array", items: { type: "string" }, description: "Local file paths to upload." },
      },
      required: ["paths"],
    },
  },
  {
    name: "browser_network_requests",
    description: "List captured network requests. Set activeOnly=true for in-flight only.",
    inputSchema: {
      type: "object",
      properties: { activeOnly: { type: "boolean" } },
    },
  },
  {
    name: "browser_network_request",
    description: "Get details for a single network request by stable id from browser_network_requests. Legacy zero-based index is also accepted.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string" },
        index: { type: "number", description: "Legacy zero-based index into the retained request list" },
        details: { type: "boolean", description: "Include response body preview when true" },
      },
    },
  },
  {
    name: "browser_console_messages",
    description: "List captured console messages (log / warn / error etc.).",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_resize",
    description: "Resize the active page viewport.",
    inputSchema: {
      type: "object",
      properties: {
        width: { type: "number", description: "Viewport width in pixels" },
        height: { type: "number", description: "Viewport height in pixels" },
      },
      required: ["width", "height"],
    },
  },
  {
    name: "browser_drag",
    description: "Drag an element from source to target by CSS selector or aria ref.",
    inputSchema: {
      type: "object",
      properties: {
        source: { type: "object", description: "{ selector|ref, frameSelector? }" },
        target: { type: "object", description: "{ selector|ref, frameSelector? }" },
        timeout: { type: "number" },
      },
    },
  },
  {
    name: "browser_fill_form",
    description: "Fill multiple form fields at once. Each field needs selector or ref, and value.",
    inputSchema: {
      type: "object",
      properties: {
        fields: {
          type: "array",
          items: {
            type: "object",
            properties: {
              selector: { type: "string" },
              ref: { type: "string" },
              frameSelector: { type: "string", description: "Optional iframe CSS selector for this field." },
              name: { type: "string" },
              value: { type: "string" },
            },
            required: ["value"],
          },
        },
        timeout: { type: "number" },
      },
      required: ["fields"],
    },
  },
  {
    name: "browser_run_code_unsafe",
    description: "Execute arbitrary JavaScript in page context. Prefer browser_evaluate when possible.",
    inputSchema: {
      type: "object",
      properties: {
        script: { type: "string" },
        args: { type: "array", items: {} },
      },
      required: ["script"],
    },
  },
  {
    name: "browser_network_state_set",
    description: "Set network state: pass offline=true to simulate offline, offline=false to restore connectivity.",
    inputSchema: {
      type: "object",
      properties: { offline: { type: "boolean" } },
      required: ["offline"],
    },
  },
  {
    name: "browser_api_request",
    description: "Make an HTTP request reusing the browser session's cookies/storage (authenticated API calls without re-login). Returns status, headers, and body.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string" },
        method: { type: "string", enum: ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] },
        headers: { type: "object", description: "Request headers as key/value strings." },
        data: { description: "Request body: a string, or an object (sent as JSON)." },
        timeout: { type: "number" },
        maxBytes: { type: "number", description: "Truncate response body to this many chars. Default 100000." },
      },
      required: ["url"],
    },
  },
  {
    name: "browser_get_visible_text",
    description: "Get the visible text (document.body.innerText) of the active page. Lighter than a full aria snapshot.",
    inputSchema: {
      type: "object",
      properties: { maxLength: { type: "number", description: "Truncate to this many chars. Default 100000." } },
    },
  },
  {
    name: "browser_get_visible_html",
    description: "Get page HTML, optionally scoped to a selector. Strips script/style/svg by default for token efficiency.",
    inputSchema: {
      type: "object",
      properties: {
        selector: { type: "string", description: "Limit to this element's outerHTML. Default whole document." },
        removeScripts: { type: "boolean", description: "Remove script/style/noscript/svg. Default true." },
        maxLength: { type: "number", description: "Truncate to this many chars. Default 100000." },
      },
    },
  },
  {
    name: "browser_iframe_click",
    description: "Shorthand for clicking inside an iframe. (Most tools now accept a frameSelector directly — prefer browser_click with frameSelector.)",
    inputSchema: {
      type: "object",
      properties: {
        frameSelector: { type: "string", description: "CSS selector for the iframe element." },
        selector: { type: "string", description: "CSS selector for the target element inside the iframe." },
        timeout: { type: "number" },
      },
      required: ["frameSelector", "selector"],
    },
  },
  {
    name: "browser_iframe_fill",
    description: "Shorthand for filling inside an iframe. (Most tools now accept a frameSelector directly — prefer browser_fill with frameSelector.)",
    inputSchema: {
      type: "object",
      properties: {
        frameSelector: { type: "string", description: "CSS selector for the iframe element." },
        selector: { type: "string", description: "CSS selector for the input inside the iframe." },
        value: { type: "string" },
        timeout: { type: "number" },
      },
      required: ["frameSelector", "selector", "value"],
    },
  },
  {
    name: "browser_route_block",
    description: "Block requests by resource type and/or URL pattern (e.g. block images/fonts/media to speed up loads and shrink fingerprint surface). Applies to all pages in the context.",
    inputSchema: {
      type: "object",
      properties: {
        urlPattern: { type: "string", description: "Glob/URL pattern to match. Default **/* (all)." },
        resourceTypes: {
          type: "array",
          items: { type: "string", enum: ["document", "stylesheet", "image", "media", "font", "script", "texttrack", "xhr", "fetch", "eventsource", "websocket", "manifest", "other"] },
          description: "Resource types to abort. If omitted, blocks every request matching urlPattern.",
        },
      },
    },
  },
  {
    name: "browser_route_mock",
    description: "Mock matching requests with a canned response (fulfill). Useful for stubbing APIs or bypassing endpoints.",
    inputSchema: {
      type: "object",
      properties: {
        urlPattern: { type: "string", description: "Glob/URL pattern to match." },
        status: { type: "number", description: "HTTP status, default 200." },
        body: { type: "string", description: "Response body." },
        contentType: { type: "string", description: "Content-Type, default text/plain." },
      },
      required: ["urlPattern"],
    },
  },
  {
    name: "browser_route_clear",
    description: "Remove all active block/mock routes.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_storage_save",
    description: "Export current session (cookies + localStorage) as a Playwright storageState. Saves to path, or returns the state JSON if path omitted.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Output JSON file path. If omitted, returns the state inline." },
      },
    },
  },
  {
    name: "browser_storage_load",
    description: "Restore a session from a storageState (cookies + localStorage). Provide a file path or an inline state object. Note: localStorage restore navigates to each origin.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Path to a storageState JSON file." },
        state: { type: "object", description: "Inline storageState object ({ cookies, origins })." },
      },
    },
  },
  {
    name: "browser_cookie_list",
    description: "List cookies in the current session, optionally filtered by domain and/or path.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Filter cookies by domain (substring match)." },
        path: { type: "string", description: "Filter cookies by path (exact match)." },
      },
    },
  },
  {
    name: "browser_cookie_get",
    description: "Get a single cookie by name. Returns null if not present.",
    inputSchema: {
      type: "object",
      properties: { name: { type: "string", description: "Cookie name to get." } },
      required: ["name"],
    },
  },
  {
    name: "browser_cookie_set",
    description: "Set a cookie with optional flags. Provide url, or domain (path defaults to /). If neither given, the active page's origin is used.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string" },
        value: { type: "string" },
        url: { type: "string", description: "URL the cookie applies to. Alternative to domain/path." },
        domain: { type: "string", description: "Cookie domain, e.g. .example.com" },
        path: { type: "string", description: "Cookie path, default /." },
        expires: { type: "number", description: "Expiry as Unix timestamp (seconds). Session cookie if omitted." },
        httpOnly: { type: "boolean" },
        secure: { type: "boolean" },
        sameSite: { type: "string", enum: ["Strict", "Lax", "None"] },
      },
      required: ["name", "value"],
    },
  },
  {
    name: "browser_cookie_delete",
    description: "Delete cookies by name, optionally narrowed by domain/path.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Cookie name to delete." },
        domain: { type: "string" },
        path: { type: "string" },
      },
      required: ["name"],
    },
  },
  {
    name: "browser_cookie_clear",
    description: "Clear all cookies in the current session.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_localstorage_list",
    description: "List all localStorage key-value pairs for the active page's origin.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_localstorage_get",
    description: "Get a localStorage item by key. Returns null if absent.",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string" } },
      required: ["key"],
    },
  },
  {
    name: "browser_localstorage_set",
    description: "Set a localStorage item on the active page's origin.",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string" }, value: { type: "string" } },
      required: ["key", "value"],
    },
  },
  {
    name: "browser_localstorage_delete",
    description: "Delete a localStorage item by key.",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string" } },
      required: ["key"],
    },
  },
  {
    name: "browser_localstorage_clear",
    description: "Clear all localStorage for the active page's origin.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_sessionstorage_list",
    description: "List all sessionStorage key-value pairs for the active page's origin.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_sessionstorage_get",
    description: "Get a sessionStorage item by key. Returns null if absent.",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string" } },
      required: ["key"],
    },
  },
  {
    name: "browser_sessionstorage_set",
    description: "Set a sessionStorage item on the active page's origin.",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string" }, value: { type: "string" } },
      required: ["key", "value"],
    },
  },
  {
    name: "browser_sessionstorage_delete",
    description: "Delete a sessionStorage item by key.",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string" } },
      required: ["key"],
    },
  },
  {
    name: "browser_sessionstorage_clear",
    description: "Clear all sessionStorage for the active page's origin.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_passkey_install",
    description: "Install Patchright's virtual WebAuthn authenticator in the current browser context. Call before a page first uses navigator.credentials.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_passkey_create",
    description: "Generate or import a virtual passkey. To import, provide all four key-material fields. Private keys are omitted unless includePrivateKey=true.",
    inputSchema: {
      type: "object",
      properties: {
        rpId: { type: "string", description: "Relying-party id, usually the site's effective domain." },
        id: { type: "string", description: "Base64url credential id." },
        userHandle: { type: "string", description: "Base64url user handle." },
        privateKey: { type: "string", description: "Base64url PKCS#8 DER private key." },
        publicKey: { type: "string", description: "Base64url SPKI DER public key." },
        includePrivateKey: { type: "boolean", description: "Return private key material. Default false." },
      },
      required: ["rpId"],
    },
  },
  {
    name: "browser_passkey_list",
    description: "List virtual passkeys, optionally filtered by rpId or credential id. Private keys are omitted unless includePrivateKey=true.",
    inputSchema: {
      type: "object",
      properties: {
        rpId: { type: "string" },
        id: { type: "string", description: "Base64url credential id." },
        includePrivateKey: { type: "boolean", description: "Return private key material. Default false." },
      },
    },
  },
  {
    name: "browser_passkey_delete",
    description: "Delete one virtual passkey by its base64url credential id.",
    inputSchema: {
      type: "object",
      properties: { id: { type: "string" } },
      required: ["id"],
    },
  },
  {
    name: "browser_video_save",
    description: "Direct the active page's session recording to a specific output path (requires the session to have been started with recordVideo). The .webm finalizes when the page or browser closes. Without a path, returns the pending video location.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Target .webm path. If omitted, returns the auto-generated pending path." },
      },
    },
  },
  {
    name: "browser_highlight",
    description: "Draw a persistent highlight overlay around an element (by CSS selector or aria ref). Useful for screenshots and video recording to show what the agent is focusing on. Does not affect page behavior.",
    inputSchema: {
      type: "object",
      properties: {
        ...targetProperties,
        label: { type: "string", description: "Optional text label shown above the highlight; also used as the key for browser_hide_highlight." },
        style: { type: "string", description: "Optional extra inline CSS for the overlay, e.g. 'outline: 3px dashed lime'." },
      },
    },
  },
  {
    name: "browser_hide_highlight",
    description: "Remove highlight overlays. Pass label/selector/ref to remove a specific one, or omit all to clear every highlight.",
    inputSchema: {
      type: "object",
      properties: {
        label: { type: "string", description: "Label/key used when the highlight was added." },
        selector: { type: "string", description: "Selector used when the highlight was added." },
        ref: { type: "string", description: "aria ref used when the highlight was added." },
      },
    },
  },
  {
    name: "browser_save_pdf",
    description: "Render the active page to PDF via CDP (works in headed/stealth mode). Saves to path, or returns base64 if path omitted.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Output file path. If omitted, returns base64." },
        landscape: { type: "boolean" },
        printBackground: { type: "boolean", description: "Include background graphics. Default true." },
        scale: { type: "number", description: "Render scale, default 1." },
        format: { type: "string", enum: ["Letter", "Legal", "Tabloid", "A3", "A4", "A5"] },
      },
    },
  },
  {
    name: "browser_close",
    description: "Close the browser session.",
    inputSchema: { type: "object", properties: {} },
  },
];

export const tools: Tool[] = extendBrowserTools(upstreamTools);
