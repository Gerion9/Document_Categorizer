import type { Section } from "../types";

export function flattenSections(sections: Section[]): Section[] {
  const flattened: Section[] = [];
  for (const section of sections) {
    flattened.push(section);
    if (section.children?.length) {
      flattened.push(...flattenSections(section.children));
    }
  }
  return flattened;
}
