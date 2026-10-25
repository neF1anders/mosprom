import type { Raster } from "./stl";

export type Preview = { image: string } | { text: string[] } | null;

// размер предпросмотра
const WIDTH = 320;
const cache = new Map<string, Promise<Preview>>();

export function preview(
  key: string,
  kind: string,
  load: () => Promise<Blob>,
): Promise<Preview> {
  let result = cache.get(key);
  if (!result) {
    result = load()
      .then((blob) => render(kind, blob))
      .catch(() => null);
    cache.set(key, result);
  }
  return result;
}

export function forget(key: string) {
  void cache.get(key)?.then((value) => {
    if (value && "image" in value) URL.revokeObjectURL(value.image);
  });
  cache.delete(key);
}

async function render(kind: string, blob: Blob): Promise<Preview> {
  switch (kind) {
    case "png":
    case "jpg":
    case "jpeg":
      return { image: URL.createObjectURL(blob) };
    case "txt":
    case "md":
      return text(await blob.slice(0, 4096).text());
    case "docx":
      return text(await docxText(blob));
    case "pdf":
      return { image: await pdfPage(blob) };
    case "stl":
      return { image: await stlImage(blob) };
    default:
      return null;
  }
}

function text(value: string): Preview {
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.replace(/^#+\s*/, "").trim())
    .filter(Boolean)
    .slice(0, 8)
    .map((line) => line.slice(0, 200));
  return lines.length ? { text: lines } : null;
}

async function docxText(blob: Blob) {
  const xml = await zipEntry(
    new Uint8Array(await blob.arrayBuffer()),
    "word/document.xml",
  );
  const document = new DOMParser().parseFromString(xml, "application/xml");
  const w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
  return Array.from(document.getElementsByTagNameNS(w, "p"), (paragraph) =>
    Array.from(
      paragraph.getElementsByTagNameNS(w, "t"),
      (run) => run.textContent,
    ).join(""),
  ).join("\n");
}

// запись ZIP-контейнера
async function zipEntry(bytes: Uint8Array, name: string) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let end = bytes.length - 22;
  while (end >= 0 && view.getUint32(end, true) !== 0x06054b50) end--;
  if (end < 0) throw new Error("not a zip");
  let entry = view.getUint32(end + 16, true);
  for (let i = view.getUint16(end + 10, true); i > 0; i--) {
    const nameLength = view.getUint16(entry + 28, true);
    const entryName = new TextDecoder().decode(
      bytes.subarray(entry + 46, entry + 46 + nameLength),
    );
    if (entryName === name) {
      const method = view.getUint16(entry + 10, true);
      const size = view.getUint32(entry + 20, true);
      const local = view.getUint32(entry + 42, true);
      const start =
        local +
        30 +
        view.getUint16(local + 26, true) +
        view.getUint16(local + 28, true);
      const data = bytes.slice(start, start + size);
      if (method === 0) return new TextDecoder().decode(data);
      const stream = new Blob([data])
        .stream()
        .pipeThrough(new DecompressionStream("deflate-raw"));
      return new Response(stream).text();
    }
    entry +=
      46 +
      nameLength +
      view.getUint16(entry + 30, true) +
      view.getUint16(entry + 32, true);
  }
  throw new Error(`${name} not found`);
}

async function pdfPage(blob: Blob) {
  const [pdfjs, worker] = await Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
  ]);
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  const task = pdfjs.getDocument({
    data: new Uint8Array(await blob.arrayBuffer()),
  });
  try {
    const page = await (await task.promise).getPage(1);
    const viewport = page.getViewport({
      scale: WIDTH / page.getViewport({ scale: 1 }).width,
    });
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);
    await page.render({ canvas, viewport }).promise;
    return await objectUrl(canvas);
  } finally {
    await task.destroy();
  }
}

async function stlImage(blob: Blob) {
  const buffer = await blob.arrayBuffer();
  const raster = await new Promise<Raster>((resolve, reject) => {
    const worker = new Worker(new URL("./stl.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.onmessage = (event: MessageEvent<Raster>) => {
      worker.terminate();
      resolve(event.data);
    };
    worker.onerror = (event) => {
      worker.terminate();
      reject(event);
    };
    worker.postMessage({ buffer, width: WIDTH * 2, height: 84 * 4 }, [buffer]);
  });
  const canvas = document.createElement("canvas");
  canvas.width = raster.width;
  canvas.height = raster.height;
  canvas
    .getContext("2d")!
    .putImageData(
      new ImageData(
        new Uint8ClampedArray(raster.data),
        raster.width,
        raster.height,
      ),
      0,
      0,
    );
  return objectUrl(canvas);
}

function objectUrl(canvas: HTMLCanvasElement) {
  return new Promise<string>((resolve, reject) =>
    canvas.toBlob(
      (blob) =>
        blob ? resolve(URL.createObjectURL(blob)) : reject(new Error("empty")),
      "image/png",
    ),
  );
}
