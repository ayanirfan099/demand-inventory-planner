import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

/**
 * WCAG 2.1 A/AA audit of the current page.
 *
 * Returns one readable line per violation (rule, impact, failing selector, and what the rule
 * expected) instead of a Playwright diff on a nested object: a failure has to be actionable from
 * the CI annotation alone, because Actions logs are not always reachable.
 */
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

export async function auditPage(page: Page, label: string): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();

  return results.violations.map((violation) => {
    const nodes = violation.nodes
      .slice(0, 3)
      .map((node) => {
        const summary = (node.failureSummary ?? "").replace(/\s+/g, " ").trim();
        return `${node.target.join(" ")} -> ${summary.slice(0, 200)}`;
      })
      .join(" | ");
    return `[${label}] ${violation.id} (${violation.impact ?? "unknown"}): ${violation.help} :: ${nodes}`;
  });
}

/** Asserts the page is clean, printing every violation when it is not. */
export async function expectAccessible(page: Page, label: string): Promise<void> {
  const failures = await auditPage(page, label);
  if (failures.length > 0) {
    throw new Error(`${failures.length} WCAG violation(s):\n${failures.join("\n")}`);
  }
}
