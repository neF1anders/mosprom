import type { Geometry } from "./types";

// Model size with its scale; before the user confirms one, the size is in file units.
export function modelSize(geometry?: Geometry | null) {
  if (!geometry?.extents.length) return "";
  const size = geometry.extents.map((x) => Number(x.toFixed(3))).join(" × ");
  const units =
    geometry.units === "unknown" ? "в единицах файла" : geometry.units;
  return `${size} ${units}`;
}
