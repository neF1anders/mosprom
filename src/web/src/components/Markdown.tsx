import type { ReactNode } from "react";
import styles from "../App.module.css";

interface Block {
  kind: "heading" | "list" | "ordered" | "paragraph";
  lines: string[];
}
const HEADING = /^#{1,6}\s+/;
const BULLET = /^\s*[-*•]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;

function kindOf(line: string): Block["kind"] {
  if (HEADING.test(line)) return "heading";
  if (BULLET.test(line)) return "list";
  return NUMBER.test(line) ? "ordered" : "paragraph";
}
// Lines of one kind in a row make one block; an empty line ends a paragraph.
export function blocks(text: string): Block[] {
  const result: Block[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) {
      result.push({ kind: "paragraph", lines: [] });
      continue;
    }
    const kind = kindOf(line);
    const last = result.at(-1);
    if (last && last.kind === kind && kind !== "heading" && last.lines.length)
      last.lines.push(line);
    else result.push({ kind, lines: [line] });
  }
  return result.filter((block) => block.lines.length);
}
function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return <code key={index}>{part.slice(1, -1)}</code>;
    if (/^([*_]).+\1$/.test(part))
      return <em key={index}>{part.slice(1, -1)}</em>;
    return part;
  });
}
function strip(line: string) {
  return line.replace(HEADING, "").replace(BULLET, "").replace(NUMBER, "");
}
// The assistant writes Markdown: headings, lists, paragraphs and inline marks are shown,
// anything else stays text. React escapes it, so a model's HTML never reaches the page.
export function Markdown({ text }: { text: string }) {
  return (
    <div className={styles.markdown}>
      {blocks(text).map((block, index) => {
        if (block.kind === "heading")
          return <h3 key={index}>{inline(strip(block.lines[0]))}</h3>;
        if (block.kind === "paragraph")
          return <p key={index}>{inline(block.lines.join("\n"))}</p>;
        const items = block.lines.map((line, item) => (
          <li key={item}>{inline(strip(line))}</li>
        ));
        return block.kind === "list" ? (
          <ul key={index}>{items}</ul>
        ) : (
          <ol key={index}>{items}</ol>
        );
      })}
    </div>
  );
}
