"""Page extraction and result application for all catalog families.

Custom applications use explicit recipes. Extraction never substitutes guessed
dynamic challenge parameters and application never implies backend acceptance.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from capsolver_mcp.api import ApiError


CAPTURE_SCRIPT = r"""
(() => {
  const captured = [];
  Object.defineProperty(window, '__capsolverCaptured', {value: captured, configurable: false});
  const hooked = new WeakMap();
  const watch = (object, key, transform) => {
    if (!Object.isExtensible(object)) return;
    const descriptor = Object.getOwnPropertyDescriptor(object, key);
    // Do not replace application-defined accessors or immutable SDK properties.
    if (descriptor && (!descriptor.configurable || descriptor.get || descriptor.set)) {
      if (descriptor.writable) object[key] = transform(object[key]);
      return;
    }
    let value = transform(object[key]);
    Object.defineProperty(object, key, {
      configurable: true, enumerable: descriptor ? descriptor.enumerable : true,
      get: () => value, set: next => { value = transform(next); }
    });
  };
  const hook = (api, name) => {
    if (!api || !['object', 'function'].includes(typeof api)) return;
    const names = hooked.get(api) || new Set();
    if (names.has(name)) return;
    names.add(name); hooked.set(api, names);
    watch(api, 'render', original => typeof original !== 'function' ? original : function(container, options) {
      const entry = {name, container, options: {...(options || {})}};
      captured.push(entry);
      entry.widgetId = original.apply(this, arguments);
      return entry.widgetId;
    });
    watch(api, 'execute', original => typeof original !== 'function' ? original : function(key, options) {
      captured.push({name, executeKey: typeof key === 'string' ? key : null, options: {...(options || {})}});
      return original.apply(this, arguments);
    });
    if (name === 'grecaptcha') watch(api, 'enterprise', value => {
      hook(value, 'grecaptcha.enterprise'); return value;
    });
  };
  for (const name of ['turnstile', 'grecaptcha']) {
    try { watch(window, name, value => { hook(value, name); return value; }); } catch (_) {}
  }
})();
"""


EXTRACT_SCRIPT = r"""() => {
 const found = [];
 const push = (kind, task, selector, meta={}) => found.push({kind, task, selector, ...meta});
 for (const [index, e] of [...document.querySelectorAll('.cf-turnstile, .g-recaptcha, [data-captcha-type]')].entries()) {
   const custom = e.getAttribute('data-captcha-type');
   const type = custom || (e.matches('.cf-turnstile') ? 'AntiTurnstileTaskProxyLess' : 'ReCaptchaV2TaskProxyLess');
   const task = {type, websiteURL: location.href};
   const key = e.getAttribute('data-sitekey'); if (key) task.websiteKey = key;
   const action = e.getAttribute('data-action'), cdata = e.getAttribute('data-cdata');
   if (type === 'AntiTurnstileTaskProxyLess' && (action || cdata)) task.metadata = {...(action ? {action}:{}), ...(cdata ? {cdata}: {})};
   if (type.startsWith('ReCaptcha') && action) task.pageAction = action;
   const selector = e.id ? '#' + CSS.escape(e.id) : (custom ? '[data-captcha-type]' : (type === 'AntiTurnstileTaskProxyLess' ? '.cf-turnstile' : '.g-recaptcha'));
   let extra = {};
   try {extra = JSON.parse(e.getAttribute('data-capsolver-task') || '{}')} catch (_) {}
   push(type, {...task, ...extra, type, websiteURL:location.href}, selector, {revision: e.getAttribute('data-challenge-revision') || '', widget_index:index});
 }
 const captures = window.__capsolverCaptured || [];
 captures.forEach((c, i) => {
   const options = c.options || {}, sitekey = options.sitekey || c.executeKey;
   if (!sitekey) return;
   const version = c.executeKey ? 'V3' : 'V2';
   const type = c.name === 'turnstile' ? 'AntiTurnstileTaskProxyLess' :
     ('ReCaptcha' + version + (c.name.includes('enterprise') ? 'Enterprise':'') + 'TaskProxyLess');
   const task = {type, websiteURL:location.href, websiteKey:sitekey};
   if (options.action) task[type.startsWith('ReCaptcha') ? 'pageAction' : 'metadata'] = type.startsWith('ReCaptcha') ? options.action : {action:options.action};
   if (options.cData) task.metadata = {...task.metadata,cdata:options.cData};
   if (type.includes('Enterprise') && typeof options.s === 'string' && options.s) task.enterprisePayload = {s:options.s};
   const existing=found.find(f => f.task.websiteKey === sitekey);
   if(existing) {
     // A new V3 execute call is an authoritative parameter snapshot. Do not
     // retain a dynamic payload/action omitted by the latest invocation.
     if (existing.capture_index !== undefined && type.startsWith('ReCaptchaV3')) {
       delete existing.task.enterprisePayload; delete existing.task.pageAction;
     }
     existing.capture_index=i; existing.widget_id=c.widgetId; existing.kind=type;
     existing.task={...existing.task,...task};
   }
   else push(type,task,null,{capture_index:i, widget_id:c.widgetId});
 });
 for (const e of document.querySelectorAll('iframe[src]')) {
   let u; try {u = new URL(e.src)} catch (_) {continue}
   if (/recaptcha\/(api2|enterprise)\/anchor/.test(u.pathname)) {
     const key=u.searchParams.get('k');
     if (key && !found.some(f => f.task.websiteKey === key)) {
       const type = u.pathname.includes('enterprise') ? 'ReCaptchaV2EnterpriseTaskProxyLess':'ReCaptchaV2TaskProxyLess';
       const task = {type,websiteURL:location.href,websiteKey:key};
       if (u.searchParams.get('sa')) task.pageAction=u.searchParams.get('sa');
       if (u.searchParams.get('s')) {if(type.includes('Enterprise')) task.enterprisePayload={s:u.searchParams.get('s')}; else task.recaptchaDataSValue=u.searchParams.get('s')}
       if (u.searchParams.get('size')==='invisible') task.isInvisible=true;
       push(type,task,null);
     }
   }
 }
 if (window.gokuProps && window.gokuProps.key) {
   const g=window.gokuProps, script=[...document.scripts].find(s => /challenge\.js/.test(s.src));
   push('AntiAwsWafTaskProxyLess',{type:'AntiAwsWafTaskProxyLess',websiteURL:location.href,awsKey:g.key,awsIv:g.iv,awsContext:g.context,...(script?{awsChallengeJS:script.src}:{})},null);
 }
 const dd = [...document.querySelectorAll('iframe[src]')].find(e => /captcha-delivery\.com/.test(e.src));
 if(dd) push('DatadomeSliderTask',{type:'DatadomeSliderTask',captchaUrl:dd.src,userAgent:navigator.userAgent},null);
 const mt=document.querySelector('.mtcaptcha[data-sitekey]');
 if(mt) push('MtCaptchaTaskProxyLess',{type:'MtCaptchaTaskProxyLess',websiteURL:location.href,websiteKey:mt.getAttribute('data-sitekey')},null);
 if (document.querySelector('script[src*="/cdn-cgi/challenge-platform/"]') && !found.some(f=>f.kind==='AntiTurnstileTaskProxyLess'))
   push('AntiCloudflareTask',{type:'AntiCloudflareTask',websiteURL:location.href,userAgent:navigator.userAgent},null);
 return found;
}"""


def fingerprint(task: dict[str, Any], revision: str, frame_url: str) -> str:
    if task.get("type") == "AntiCloudflareTask":
        # Cloudflare can refresh its transport token while solving the same
        # protected resource. Keep origin/path and every business query field
        # strict; this exception does not apply to widget-token challenges.
        def protected_resource(url: str) -> str:
            parts = urlsplit(url)
            query = [
                (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "__cf_chl_rt_tk"
            ]
            return urlunsplit(parts._replace(query=urlencode(query)))

        frame_url = protected_resource(frame_url)
        task = dict(task)
        if isinstance(task.get("websiteURL"), str):
            task["websiteURL"] = protected_resource(task["websiteURL"])
    return hashlib.sha256(json.dumps([task, revision, frame_url], sort_keys=True, allow_nan=False).encode()).hexdigest()


async def screenshot_input(frame: Any, selector: str) -> str:
    locator = frame.locator(selector)
    if await locator.count() != 1:
        raise ValueError("Image selector must match exactly one element.")
    return base64.b64encode(await locator.screenshot()).decode()


async def extract_recipe(page: Any, frame: Any, recipe: dict[str, Any], *, local_only: bool = False) -> dict[str, Any]:
    task = dict(recipe.get("task", {}))
    if not isinstance(task.get("type"), str):
        raise ValueError("Recipe requires an explicit task.type.")
    task.setdefault("websiteURL", page.url)
    for field, spec in recipe.get("parameters", {}).items():
        if not isinstance(spec, dict) or not spec.get("selector"):
            raise ValueError("Each extracted parameter requires a selector.")
        locator = frame.locator(spec["selector"])
        if await locator.count() != 1:
            raise ValueError("Parameter selector must match exactly one element.")
        if spec.get("attribute"):
            value = await locator.get_attribute(spec["attribute"])
        else:
            value = await locator.input_value() if spec.get("source") == "value" else await locator.inner_text()
        if value is None or value == "":
            raise ValueError("A dynamic recipe parameter is empty.")
        task[field] = json.loads(value) if spec.get("json") else value
    images = recipe.get("images", {})

    async def image_data(spec: Any) -> str:
        if isinstance(spec, str):
            return await screenshot_input(frame, spec)
        if not isinstance(spec, dict) or spec.get("source") != "image_bytes" or not spec.get("selector"):
            raise ValueError("Image input requires a selector or an image_bytes specification.")
        source = await frame.locator(spec["selector"]).evaluate("e=>e.currentSrc||e.src||''")
        if source.startswith("data:"):
            header, encoded = source.split(",", 1)
            if ";base64" not in header:
                raise ValueError("Raw data images must use Base64 encoding.")
            base64.b64decode(encoded, validate=True)
            return str(encoded)
        if urlparse(source).scheme not in {"http", "https"}:
            raise ValueError("Raw image extraction requires an HTTP(S) or Base64 data image.")
        if local_only:
            from capsolver_mcp.browser.session_manager import is_loopback_url

            if not is_loopback_url(source):
                raise ValueError("Offline raw image extraction allows loopback images only.")
        response = await page.context.request.get(source, timeout=10000, max_redirects=0)
        if not response.ok:
            raise ValueError("The original image could not be fetched in the current session.")
        data = await response.body()
        if len(data) > 9_000_000:
            raise ValueError("Raw image exceeds the supported local extraction size.")
        return base64.b64encode(data).decode()

    for field, selectors in images.items():
        task[field] = (
            [await image_data(s) for s in selectors] if isinstance(selectors, list) else await image_data(selectors)
        )
    return task


async def _install_cookies(page: Any, cookies: list[dict[str, Any]], *, attached: bool, verify: bool = False) -> None:
    def check(stored: list[dict[str, Any]]) -> None:
        if any(not any(item["name"] == cookie["name"] and item["value"] == cookie["value"]
                       and item["domain"].lstrip(".") == cookie["domain"].lstrip(".")
                       and item["path"] == cookie["path"] for item in stored) for cookie in cookies):
            raise ValueError("The solution cookie is not available to the target page after installation.")

    if not attached:
        await page.context.add_cookies(cookies)
        if verify:
            check(await page.context.cookies([page.url]))
        return
    # A CDP client can see a tab in an external isolated context while its
    # browser-level cookie API still points to Chromium's default context.
    target = await page.context.new_cdp_session(page)
    try:
        for cookie in cookies:
            result = await target.send("Network.setCookie", cookie)
            if not result.get("success"):
                raise ValueError("Chromium rejected the solution cookie for the attached tab.")
        if verify:
            check((await target.send("Network.getCookies", {"urls": [page.url]}))["cookies"])
    finally:
        await target.detach()


def _datadome_cookie(raw: Any, page_url: str) -> dict[str, Any]:
    """Validate the complete result before performing any browser mutation."""
    from http.cookies import CookieError, SimpleCookie
    from email.utils import parsedate_to_datetime
    import time

    invalid = "The DataDome result requires one nonempty datadome cookie scoped to the current page."
    if not isinstance(raw, str) or not raw or "\r" in raw or "\n" in raw:
        raise ValueError(invalid)
    try:
        parsed = SimpleCookie(raw)
    except CookieError:
        raise ValueError(invalid) from None
    if set(parsed) != {"datadome"} or not parsed["datadome"].value:
        raise ValueError(invalid)
    morsel = parsed["datadome"]
    page = urlsplit(page_url)
    host = page.hostname or ""
    domain = morsel["domain"] or host
    scope = domain.removeprefix(".").lower()
    path = morsel["path"] or "/"
    page_path = page.path or "/"
    if (page.scheme not in {"http", "https"} or not scope
            or not (host == scope or host.endswith("." + scope))
            or not path.startswith("/")
            or not (page_path == path or page_path.startswith(path if path.endswith("/") else path + "/"))):
        raise ValueError(invalid)
    cookie: dict[str, Any] = {"name": "datadome", "value": morsel.value, "domain": domain, "path": path}
    for field, source in (("secure", "secure"), ("httpOnly", "httponly")):
        if morsel[source]:
            cookie[field] = True
    if morsel["samesite"]:
        if morsel["samesite"].lower() not in {"lax", "strict", "none"}:
            raise ValueError(invalid)
        cookie["sameSite"] = morsel["samesite"].capitalize()
    try:
        if morsel["max-age"]:
            cookie["expires"] = time.time() + int(morsel["max-age"])
        elif morsel["expires"]:
            cookie["expires"] = parsedate_to_datetime(morsel["expires"]).timestamp()
        if "expires" in cookie and cookie["expires"] <= time.time():
            raise ValueError
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError("The returned cookie expiration is invalid.") from None
    return cookie


async def apply_solution(
    page: Any,
    frame: Any,
    task: dict[str, Any],
    solution: dict[str, Any],
    recipe: dict[str, Any],
    detected: dict[str, Any],
    *,
    attached: bool = False,
) -> dict[str, Any]:
    """Apply through explicit mappings, captured callbacks, or well-known response fields."""
    if "rects" in solution:
        rects = solution["rects"]
        fields = ("x1", "y1", "x2", "y2")
        if not isinstance(rects, list) or any(
            not isinstance(rect, dict)
            or any(
                isinstance(rect.get(key), bool)
                or not isinstance(rect.get(key), (int, float))
                or not math.isfinite(rect[key])
                for key in fields
            )
            or rect["x2"] <= rect["x1"] or rect["y2"] <= rect["y1"]
            for rect in rects
        ):
            raise ApiError("INVALID_PROVIDER_SOLUTION", "Provider rectangles require finite x1, y1, x2, y2 coordinates with positive width and height.")
    name = task["type"]
    datadome_cookie = _datadome_cookie(solution.get("cookie"), page.url) if name == "DatadomeSliderTask" else None
    result: dict[str, Any] = {"applied": False, "methods": []}
    application = recipe.get("application", {})
    for field, selector in application.get("fields", {}).items():
        if field not in solution:
            raise ValueError("Solution field required by the recipe is missing.")
        value = solution[field]
        text = value if isinstance(value, str) else json.dumps(value)
        locator = frame.locator(selector)
        if await locator.count() != 1:
            raise ValueError("Application field selector must match exactly one element.")
        await locator.evaluate(
            "(e,value) => {e.value=value; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}))}",
            text,
        )
        result["methods"].append("field:" + field)
    cookies: dict[str, str] = {}
    if isinstance(solution.get("cookies"), dict):
        cookies.update(solution["cookies"])
    if datadome_cookie:
        await _install_cookies(page, [datadome_cookie], attached=attached, verify=True)
        result["methods"].append("cookie")
    elif name.startswith("AntiAwsWaf") and solution.get("cookie"):
        cookies["aws-waf-token"] = solution["cookie"]
    elif name.startswith("ReCaptcha"):
        for key in ("recaptcha-ca-t", "recaptcha-ca-e"):
            if solution.get(key):
                cookies[key] = solution[key]
    if cookies:
        await _install_cookies(
            page, [{"name": k, "value": v, "url": page.url} for k, v in cookies.items()], attached=attached
        )
        result["methods"].append("cookies")
    token = solution.get("gRecaptchaResponse", solution.get("token"))
    if token and name != "AntiCloudflareTask":
        applied = await frame.evaluate(
            r"""({token, name, capture}) => {
          let count=0;
          const fields = name.startsWith('ReCaptcha') ? '[name="g-recaptcha-response"]' :
            name==='AntiTurnstileTaskProxyLess' ? '[name="cf-turnstile-response"]' : name.startsWith('MtCaptcha') ? '[name="mtcaptcha-verifiedtoken"]' : '';
          const elements=fields ? [...document.querySelectorAll(fields)]:[];
          if(elements.length===1) for(const e of elements) {e.value=token; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));count++}
          const captured=window.__capsolverCaptured || [];
          const candidates = capture !== null ? [captured[capture]] : [];
          for(const c of candidates) if(c && typeof c.options.callback === 'function') {c.options.callback(token); count++}
          return count;
        }""",
            {"token": token, "name": name, "capture": detected.get("capture_index")},
        )
        if applied:
            result["methods"].append("token")
    callback = application.get("callback")
    if callback:
        # Only an explicit dotted function path, never arbitrary user JavaScript.
        called = await frame.evaluate(
            r"""({path, solution}) => {
          if(!/^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/.test(path)) return false;
          let owner=window; const keys=path.split('.');
          for(const key of keys.slice(0,-1)) {owner=owner?.[key]; if(!owner)return false}
          const fn=owner[keys.at(-1)]; if(typeof fn!=='function')return false;
          fn.call(owner,solution); return true;
        }""",
            {"path": callback, "solution": solution},
        )
        if not called:
            raise ValueError("Configured application callback was not found.")
        result["methods"].append("callback")
    interaction = application.get("interaction")
    if interaction:
        target = frame.locator(interaction["selector"])
        bounds = await target.bounding_box()
        if not bounds:
            raise ValueError("Interaction target is not visible.")
        dimensions = interaction.get("image_size")
        if not dimensions or len(dimensions) != 2 or min(dimensions) <= 0:
            raise ValueError("Recognition interactions require original image_size [width,height].")
        sx, sy = bounds["width"] / dimensions[0], bounds["height"] / dimensions[1]
        points = solution.get("points")
        if solution.get("rects"):
            points = [[(r["x1"] + r["x2"]) / 2, (r["y1"] + r["y2"]) / 2] for r in solution["rects"]]
        if solution.get("box"):
            points = [solution["box"]]
        if points:
            for x, y in points:
                if not 0 <= x <= dimensions[0] or not 0 <= y <= dimensions[1]:
                    raise ValueError("Recognition point is outside the source image.")
                await page.mouse.click(bounds["x"] + x * sx, bounds["y"] + y * sy)
        elif "distance" in solution or "angle" in solution:
            handle = frame.locator(interaction["handle_selector"])
            handle_bounds = await handle.bounding_box()
            if not handle_bounds:
                raise ValueError("Interaction handle is not visible.")
            x, y = handle_bounds["x"] + handle_bounds["width"] / 2, handle_bounds["y"] + handle_bounds["height"] / 2
            distance = solution.get("distance")
            if distance is None:
                distance = solution["angle"] * interaction["pixels_per_degree"]
            await page.mouse.move(x, y)
            await page.mouse.down()
            try:
                await page.mouse.move(x + distance * sx, y, steps=12)
            finally:
                await page.mouse.up()
        elif "objects" in solution:
            cells = frame.locator(interaction["cells_selector"])
            count = await cells.count()
            for index in solution["objects"]:
                if not isinstance(index, int) or not 0 <= index < count:
                    raise ValueError("Recognition index is outside the current grid.")
                await cells.nth(index).click()
        elif solution.get("hasObject"):
            await target.click()
        else:
            raise ValueError("Solution does not contain an applicable interaction result.")
        result["methods"].append("interaction")
    result["applied"] = bool(result["methods"])
    return result
