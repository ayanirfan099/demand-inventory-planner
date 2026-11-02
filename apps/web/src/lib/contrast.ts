/**
 * WCAG contrast helpers.
 *
 * The palette lives in `globals.css` as tokens; these functions let the test suite assert the
 * pairs the UI actually uses instead of eyeballing a screenshot. Ratios follow WCAG 2.1:
 * normal text needs 4.5:1, large text (18.66px bold / 24px) needs 3:1, and non-text UI
 * boundaries need 3:1 against their neighbour.
 */

export type Rgb = { r: number; g: number; b: number };

export function parseHex(hex: string): Rgb {
  const value = hex.trim().replace(/^#/, "");
  const expanded =
    value.length === 3
      ? value
          .split("")
          .map((char) => char + char)
          .join("")
      : value;
  if (!/^[0-9a-fA-F]{6}$/.test(expanded)) {
    throw new Error(`not a hex colour: ${hex}`);
  }
  return {
    r: Number.parseInt(expanded.slice(0, 2), 16),
    g: Number.parseInt(expanded.slice(2, 4), 16),
    b: Number.parseInt(expanded.slice(4, 6), 16),
  };
}

function channel(value: number): number {
  const scaled = value / 255;
  return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  const { r, g, b } = parseHex(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** Contrast ratio between two colours, from 1 (none) to 21 (black on white). */
export function contrastRatio(foreground: string, background: string): number {
  const first = relativeLuminance(foreground);
  const second = relativeLuminance(background);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

export function meetsWcag(foreground: string, background: string, level: "AA" | "AA-large" = "AA"): boolean {
  const minimum = level === "AA-large" ? 3 : 4.5;
  return contrastRatio(foreground, background) >= minimum;
}
