import type { Geometry } from "./types";

// Model size with its scale; before the user confirms one, the size is in file units.
export function modelSize(geometry?: Geometry | null) {
  if (!geometry?.extents.length) return "";
  const size = geometry.extents.map((x) => Number(x.toFixed(3))).join(" × ");
  const units =
    geometry.units === "unknown"
      ? "в единицах файла"
      : unitNames[geometry.units] || geometry.units;
  return `${size} ${units}`;
}
const unitNames: Record<string, string> = {
  mm: "мм",
  cm: "см",
  m: "м",
  in: "дюйм",
};
// The Russian form for a count: 1 требование, 2 требования, 5 требований.
export function plural(
  count: number,
  [one, few, many]: [string, string, string],
) {
  const tens = count % 100;
  const units = count % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (units === 1) return one;
  return units >= 2 && units <= 4 ? few : many;
}
