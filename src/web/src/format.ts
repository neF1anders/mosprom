import type { Geometry } from "./types";

// размер с масштабом
export function modelSize(geometry?: Geometry | null) {
  if (!geometry?.extents.length) return "";
  const size = geometry.extents.map((x) => Number(x.toFixed(3))).join(" × ");
  const units =
    geometry.units === "unknown"
      ? "в единицах файла"
      : unitNames[geometry.units] || geometry.units;
  return `${size} ${units}`;
}
// дефекты анализа STL
export const defectLabels: Record<string, string> = {
  boundary_edges: "открытая поверхность",
  duplicate_faces: "дублирующие грани",
  multiple_shells: "несколько оболочек",
  nonmanifold_edges: "немногообразные рёбра",
  inconsistent_winding: "несогласованные нормали",
  topology_unchecked: "топология не проверена",
};
const unitNames: Record<string, string> = {
  mm: "мм",
  cm: "см",
  m: "м",
  in: "дюйм",
};
// русская форма числа
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
