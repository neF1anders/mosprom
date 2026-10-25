export interface Raster {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

const SQRT2 = Math.SQRT2,
  SQRT3 = Math.sqrt(3),
  SQRT6 = Math.sqrt(6);
// изометрическая камера
const VIEW = [1 / SQRT3, -1 / SQRT3, 1 / SQRT3];
const RIGHT = [1 / SQRT2, 1 / SQRT2, 0];
const UP = [-1 / SQRT6, 1 / SQRT6, 2 / SQRT6];
const LIGHT = normalize([0.35, -0.75, 1]);
const DARK = [142, 144, 155],
  BRIGHT = [238, 239, 242];

function normalize(v: number[]) {
  const length = Math.hypot(v[0], v[1], v[2]) || 1;
  return v.map((value) => value / length);
}

export function stlVertices(buffer: ArrayBuffer): Float32Array {
  const view = new DataView(buffer);
  const count = buffer.byteLength >= 84 ? view.getUint32(80, true) : -1;
  if (count >= 0 && 84 + count * 50 === buffer.byteLength) {
    const vertices = new Float32Array(count * 9);
    for (let i = 0; i < count; i++) {
      const offset = 84 + i * 50 + 12;
      for (let j = 0; j < 9; j++)
        vertices[i * 9 + j] = view.getFloat32(offset + j * 4, true);
    }
    return vertices;
  }
  const text = new TextDecoder().decode(buffer);
  const values: number[] = [];
  for (const match of text.matchAll(/vertex\s+(\S+)\s+(\S+)\s+(\S+)/g))
    values.push(+match[1], +match[2], +match[3]);
  return Float32Array.from(
    values.slice(0, values.length - (values.length % 9)),
  );
}

export function renderStl(
  vertices: Float32Array,
  width: number,
  height: number,
  padding = 0.1,
): Raster {
  const data = new Uint8ClampedArray(width * height * 4);
  const count = vertices.length / 9;
  if (!count) return { width, height, data };
  const screen = new Float32Array(count * 9);
  let minX = Infinity,
    maxX = -Infinity,
    minY = Infinity,
    maxY = -Infinity;
  for (let i = 0; i < count * 3; i++) {
    const x = vertices[i * 3],
      y = vertices[i * 3 + 1],
      z = vertices[i * 3 + 2];
    const sx = x * RIGHT[0] + y * RIGHT[1] + z * RIGHT[2];
    const sy = -(x * UP[0] + y * UP[1] + z * UP[2]);
    screen[i * 3] = sx;
    screen[i * 3 + 1] = sy;
    screen[i * 3 + 2] = x * VIEW[0] + y * VIEW[1] + z * VIEW[2];
    if (Number.isFinite(sx) && Number.isFinite(sy)) {
      minX = Math.min(minX, sx);
      maxX = Math.max(maxX, sx);
      minY = Math.min(minY, sy);
      maxY = Math.max(maxY, sy);
    }
  }
  const scale = Math.min(
    (width * (1 - 2 * padding)) / (maxX - minX || 1),
    (height * (1 - 2 * padding)) / (maxY - minY || 1),
  );
  const offsetX = width / 2 - ((minX + maxX) / 2) * scale,
    offsetY = height / 2 - ((minY + maxY) / 2) * scale;
  const depth = new Float32Array(width * height).fill(-Infinity);
  for (let t = 0; t < count; t++) {
    const v = t * 9;
    const ax = vertices[v + 3] - vertices[v],
      ay = vertices[v + 4] - vertices[v + 1],
      az = vertices[v + 5] - vertices[v + 2];
    const bx = vertices[v + 6] - vertices[v],
      by = vertices[v + 7] - vertices[v + 1],
      bz = vertices[v + 8] - vertices[v + 2];
    const nx = ay * bz - az * by,
      ny = az * bx - ax * bz,
      nz = ax * by - ay * bx;
    // двустороннее освещение
    const light =
      Math.abs(nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) /
      (Math.hypot(nx, ny, nz) || 1);
    const shade = 0.15 + 0.85 * light;
    const r = DARK[0] + (BRIGHT[0] - DARK[0]) * shade,
      g = DARK[1] + (BRIGHT[1] - DARK[1]) * shade,
      b = DARK[2] + (BRIGHT[2] - DARK[2]) * shade;
    const x0 = screen[v] * scale + offsetX,
      y0 = screen[v + 1] * scale + offsetY,
      z0 = screen[v + 2];
    const x1 = screen[v + 3] * scale + offsetX,
      y1 = screen[v + 4] * scale + offsetY,
      z1 = screen[v + 5];
    const x2 = screen[v + 6] * scale + offsetX,
      y2 = screen[v + 7] * scale + offsetY,
      z2 = screen[v + 8];
    const area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
    if (!area || !Number.isFinite(area)) continue;
    const left = Math.max(0, Math.floor(Math.min(x0, x1, x2))),
      right = Math.min(width - 1, Math.ceil(Math.max(x0, x1, x2))),
      top = Math.max(0, Math.floor(Math.min(y0, y1, y2))),
      bottom = Math.min(height - 1, Math.ceil(Math.max(y0, y1, y2)));
    for (let py = top; py <= bottom; py++) {
      const cy = py + 0.5;
      for (let px = left; px <= right; px++) {
        const cx = px + 0.5;
        const w0 = ((x1 - cx) * (y2 - cy) - (x2 - cx) * (y1 - cy)) / area;
        const w1 = ((x2 - cx) * (y0 - cy) - (x0 - cx) * (y2 - cy)) / area;
        const w2 = 1 - w0 - w1;
        if (w0 < 0 || w1 < 0 || w2 < 0) continue;
        const z = w0 * z0 + w1 * z1 + w2 * z2;
        const index = py * width + px;
        if (z <= depth[index]) continue;
        depth[index] = z;
        data[index * 4] = r;
        data[index * 4 + 1] = g;
        data[index * 4 + 2] = b;
        data[index * 4 + 3] = 255;
      }
    }
  }
  return { width, height, data };
}
