import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useJobEvents } from "./useJobEvents";
import { useUploads } from "./useUploads";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}
class FakeSource {
  static last: FakeSource;
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeSource.last = this;
  }
  close() {}
  emit(event_id: number, type: string) {
    const data = {
      event_id,
      revision: 1,
      type,
      status: "running",
      message: "",
      data: {},
    };
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe("event stream", () => {
  it("refetches the job for state events only", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeSource);
    const client = new QueryClient();
    const refetch = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useJobEvents("job-1", true), {
      wrapper: wrapper(client),
    });
    act(() => {
      FakeSource.last.emit(1, "tool.called");
      FakeSource.last.emit(2, "interpretation.started");
      FakeSource.last.emit(3, "checking.started");
      vi.advanceTimersByTime(200);
    });
    expect(result.current.events).toHaveLength(3);
    expect(refetch).not.toHaveBeenCalled();
    act(() => {
      FakeSource.last.emit(4, "files.completed");
      FakeSource.last.emit(5, "stage1.completed");
      vi.advanceTimersByTime(200);
    });
    // A burst of state events costs one refetch of the job and the chat list.
    expect(refetch).toHaveBeenCalledTimes(2);
  });
});
describe("uploads", () => {
  it("send every picked file to the chat they were picked in", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        urls.push(url);
        const body = url.endsWith("/attachments")
          ? { id: `a${urls.length}` }
          : {};
        return new Response(JSON.stringify(body), { status: 200 });
      }),
    );
    // A chat switch during the upload would make a later lookup return another chat.
    const ensureJob = vi
      .fn()
      .mockResolvedValueOnce("first")
      .mockResolvedValue("second");
    const client = new QueryClient();
    const { result } = renderHook(() => useUploads(ensureJob), {
      wrapper: wrapper(client),
    });
    const files = ["a.stl", "b.txt", "c.png"].map(
      (name) => new File(["x"], name),
    );
    await act(() => result.current.upload(files));
    expect(ensureJob).toHaveBeenCalledTimes(1);
    expect(urls.filter((url) => url.endsWith("/attachments"))).toEqual([
      "/api/v1/jobs/first/attachments",
      "/api/v1/jobs/first/attachments",
      "/api/v1/jobs/first/attachments",
    ]);
    expect(result.current.uploads).toEqual([]);
  });
});
