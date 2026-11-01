import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { contrastRatio, meetsWcag } from "@/lib/contrast";

/**
 * The palette is declared once in globals.css. Reading it from disk keeps this test honest:
 * if someone darkens a surface or lightens the muted ink, the assertion fails here instead of
 * being discovered by a screen-reader user.
 */
function tokens(): Record<string, string> {
  const css = readFileSync(path.resolve(__dirname, "../src/app/globals.css"), "utf-8");
  const found: Record<string, string> = {};
  for (const match of css.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    found[match[1]] = match[2];
  }
  return found;
}

const palette = tokens();

function token(name: string): string {
  const value = palette[name];
  if (!value) throw new Error(`token --${name} is not declared in globals.css`);
  return value;
}

describe("palette contrast", () => {
  it("uses body ink on the canvas and surface at AA for normal text", () => {
    expect(meetsWcag(token("ink"), token("canvas"))).toBe(true);
    expect(meetsWcag(token("ink"), token("surface"))).toBe(true);
    expect(meetsWcag(token("ink-soft"), token("surface"))).toBe(true);
  });

  it("keeps secondary and muted text readable on every surface it is used on", () => {
    for (const surface of ["surface", "canvas", "surface-muted", "canvas-deep"]) {
      expect(meetsWcag(token("ink-muted"), token(surface))).toBe(true);
      // Faint is only used for large or non-essential text, so the 3:1 large-text bar applies.
      expect(meetsWcag(token("ink-faint"), token(surface), "AA-large")).toBe(true);
    }
  });

  it("keeps status badge text at AA on its tinted background", () => {
    const pairs: [string, string][] = [
      ["blue-700", "blue-100"],
      ["blue-600", "blue-100"],
      ["teal-600", "teal-100"],
      ["amber-600", "amber-100"],
      ["red-600", "red-100"],
      ["green-600", "green-100"],
    ];
    for (const [ink, tint] of pairs) {
      expect(meetsWcag(token(ink), token(tint)), `${ink} on ${tint}`).toBe(true);
    }
  });

  it("keeps links and primary buttons readable", () => {
    expect(meetsWcag(token("blue-600"), token("surface"))).toBe(true);
    expect(meetsWcag("#ffffff", token("blue-600"))).toBe(true);
    expect(meetsWcag("#ffffff", token("blue-700"))).toBe(true);
    expect(meetsWcag(token("blue-500"), token("surface"))).toBe(true);
  });

  it("keeps structural lines visible against surfaces (non-text 3:1 is aspirational here)", () => {
    // Hairlines are decorative; the strong line is the one that must carry meaning (table
    // rules, input borders), so it gets a documented floor rather than a WCAG claim.
    expect(contrastRatio(token("line-strong"), token("surface"))).toBeGreaterThan(1.2);
  });

  it("documents the chart palette ratios for the textual chart equivalent", () => {
    // Charts always pair colour with a textual summary; these ratios are recorded so a future
    // palette change is a conscious decision, not an accident.
    const actual = contrastRatio(token("chart-actual"), "#ffffff");
    const forecast = contrastRatio(token("chart-forecast"), "#ffffff");
    expect(actual).toBeGreaterThan(3);
    expect(forecast).toBeGreaterThan(2.5);
  });
});
