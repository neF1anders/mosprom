import { describe, it, expect } from "vitest";
import { requestId } from "./api";
describe("command IDs in embedded browsers", () => {
  it.each([1, 2, 10, 100, 1000])("generates %i unique RFC4122 IDs", (count) => {
    const ids = Array.from({ length: count }, requestId);
    expect(new Set(ids).size).toBe(count);
    ids.forEach((id) =>
      expect(id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      ),
    );
  });
});
