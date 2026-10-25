import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import { renderStl, stlVertices } from "./stl";

const fixture = (name: string) => {
  const bytes = readFileSync(`../../tests/fixtures/${name}`);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length);
};
const covered = (data: Uint8ClampedArray) =>
  data.filter((_, i) => i % 4 === 3 && data[i] === 255).length;

describe("STL preview", () => {
  it("draws a binary model with shaded faces inside the frame", () => {
    const vertices = stlVertices(fixture("box.stl"));
    expect(vertices.length % 9).toBe(0);
    expect(vertices.length).toBeGreaterThan(0);
    const raster = renderStl(vertices, 160, 84);
    const pixels = covered(raster.data);
    expect(pixels).toBeGreaterThan(160 * 84 * 0.15);
    expect(pixels).toBeLessThan(160 * 84 * 0.8);
    const shades = new Set<number>();
    for (let i = 0; i < raster.data.length; i += 4)
      if (raster.data[i + 3]) shades.add(raster.data[i]);
    // свет на гранях
    expect(shades.size).toBeGreaterThanOrEqual(3);
  });
  it("reads ASCII STL", () => {
    const ascii = `solid t
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 10 0 0
vertex 0 10 0
endloop
endfacet
endsolid t`;
    const vertices = stlVertices(new TextEncoder().encode(ascii).buffer);
    expect(Array.from(vertices)).toEqual([0, 0, 0, 10, 0, 0, 0, 10, 0]);
    expect(covered(renderStl(vertices, 40, 40).data)).toBeGreaterThan(0);
  });
});
