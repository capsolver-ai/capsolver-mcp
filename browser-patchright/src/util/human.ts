import type { Locator, Page } from "patchright";

// Human-like input helpers for Patchright.
//
// Key findings that drive this implementation (measured against Patchright's
// stealth CDP keyboard, not vanilla Playwright):
//   * Holding Shift and pressing the *base* key (e.g. down("Shift")+press("1"))
//     does NOT produce the shifted glyph — Patchright ignores the separately
//     tracked modifier for text, so "!" comes out as "1" and "D" as "d".
//   * keyboard.press(actualChar, {delay}) DOES emit the correct glyph, but with
//     no Shift keydown at all (shiftKey:false), so a detector never sees a
//     modifier.
//   * The winning combination is a real Shift keyDown/keyUp *wrapped around*
//     press(actualChar): correct text AND a genuine Shift event with
//     shiftKey:true on the character's keydown.
// The press `delay` gives us per-key dwell; inter-key gaps are slept separately.

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function randInt(min: number, max: number): number {
  return Math.floor(rand(min, max + 1));
}

function sleep(page: Page, ms: number): Promise<void> {
  return ms > 0 ? page.waitForTimeout(ms) : Promise.resolve();
}

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------

// US-keyboard glyphs produced with Shift held.
const SHIFTED: Record<string, string> = {
  "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
  "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
  "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
  ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
};

const ASCII_PRINTABLE = /^[\x20-\x7e]$/;

function needsShift(ch: string): boolean {
  return (ch >= "A" && ch <= "Z") || ch in SHIFTED;
}

// Per-key dwell (keydown -> keyup) in ms.
function dwell(): number {
  return randInt(25, 100);
}

// Simple randomized gap between keys — enough to avoid a fixed cadence without
// the elaborate long-pause distribution.
function interKeyGap(): number {
  return randInt(40, 140);
}

async function typeChar(page: Page, ch: string): Promise<void> {
  if (ch === "\n") {
    await page.keyboard.press("Enter", { delay: dwell() });
    return;
  }
  if (ch === "\t") {
    await page.keyboard.press("Tab", { delay: dwell() });
    return;
  }
  if (!ASCII_PRINTABLE.test(ch)) {
    // Non-ASCII (emoji, accented, CJK): no physical key maps to it. Insert
    // directly — still fires input events on the focused element.
    await page.keyboard.insertText(ch);
    return;
  }
  const shift = needsShift(ch);
  if (shift) await page.keyboard.down("Shift");
  // press(actualChar) yields the correct glyph under Patchright; the wrapping
  // Shift down/up makes the modifier visible (shiftKey:true) to detectors.
  await page.keyboard.press(ch, { delay: dwell() });
  if (shift) await page.keyboard.up("Shift");
}

export interface HumanTypeResult {
  typed: string;
  verified: boolean;
}

// Type `textStr` into `locator` one character at a time with real per-key
// events, variable dwell, and varied inter-key gaps. When the target is an
// input/textarea and `verify` is not disabled, the resulting value is checked
// against the request and a mismatch throws — a wrong glyph is never reported
// as success, even if stealth checks would pass.
export async function humanType(
  page: Page,
  locator: Locator,
  textStr: string,
  opts: { verify?: boolean; timeout?: number } = {},
): Promise<HumanTypeResult> {
  await locator.focus({ timeout: opts.timeout });

  // Capture pre-existing value (only defined for input-like elements).
  let before: string | null = null;
  try {
    before = await locator.inputValue({ timeout: 1000 });
  } catch {
    before = null; // contenteditable / non-input: verification skipped
  }

  const chars = [...textStr];
  for (let i = 0; i < chars.length; i++) {
    await typeChar(page, chars[i]);
    if (i < chars.length - 1) await sleep(page, interKeyGap());
  }

  // Verify exact result for input-like elements with plain text (control chars
  // like Enter/Tab mutate the DOM in ways that defeat a literal comparison).
  const verifiable = opts.verify !== false && before !== null && !/[\n\t]/.test(textStr);
  let verified = false;
  if (verifiable) {
    const after = await locator.inputValue({ timeout: opts.timeout }).catch(() => null);
    if (after !== null) {
      const expected = before + textStr;
      if (after !== expected) {
        throw new Error(
          `Typing mismatch: expected=${JSON.stringify(expected)}, actual=${JSON.stringify(after)}`,
        );
      }
      verified = true;
    }
  }

  return { typed: textStr, verified };
}

// ---------------------------------------------------------------------------
// Mouse
// ---------------------------------------------------------------------------

// Click an off-center point inside the element's bounding box with a real
// press-hold. Uses a randomized sub-pixel point (never the geometric center)
// and mouse.down/up with a short hold instead of locator.click(). No synthetic
// multi-step path is generated. Falls back to locator.click() when no box is
// available.
export async function humanClick(page: Page, locator: Locator, opts: { timeout?: number } = {}): Promise<void> {
  await locator.scrollIntoViewIfNeeded({ timeout: opts.timeout }).catch(() => undefined);
  const box = await locator.boundingBox({ timeout: opts.timeout }).catch(() => null);
  if (!box || box.width <= 0 || box.height <= 0) {
    await locator.click({ timeout: opts.timeout });
    return;
  }
  const x = box.x + box.width * rand(0.35, 0.65);
  const y = box.y + box.height * rand(0.35, 0.65);
  await page.mouse.move(x, y);
  await sleep(page, randInt(25, 70));
  await page.mouse.down();
  await sleep(page, randInt(40, 110));
  await page.mouse.up();
}
