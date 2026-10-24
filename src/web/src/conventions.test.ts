import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));
function sources(folder: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) return sources(file);
    return /\.tsx?$/.test(entry.name) && !entry.name.includes(".test.")
      ? [file]
      : [];
  });
}
function nestedConditionals(file: string) {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found: string[] = [];
  // A JSX element or a function in a branch starts a new expression of its own.
  const fresh = (node: ts.Node) =>
    ts.isJsxElement(node) ||
    ts.isJsxSelfClosingElement(node) ||
    ts.isJsxFragment(node) ||
    ts.isFunctionLike(node);
  const visit = (node: ts.Node, inside: boolean) => {
    const conditional = ts.isConditionalExpression(node);
    if (conditional && inside) {
      const { line } = source.getLineAndCharacterOfPosition(node.getStart());
      found.push(`${path.relative(root, file)}:${line + 1}`);
    }
    const next = !fresh(node) && (inside || conditional);
    ts.forEachChild(node, (child) => visit(child, next));
  };
  visit(source, false);
  return found;
}
describe("code conventions", () => {
  it("a conditional expression never holds another one", () => {
    expect(sources(root).flatMap(nestedConditionals)).toEqual([]);
  });
});
