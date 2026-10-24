import { renderStl, stlVertices } from "./stl";

self.onmessage = (
  event: MessageEvent<{ buffer: ArrayBuffer; width: number; height: number }>,
) => {
  const { buffer, width, height } = event.data;
  const raster = renderStl(stlVertices(buffer), width, height);
  self.postMessage(raster, { transfer: [raster.data.buffer] });
};
