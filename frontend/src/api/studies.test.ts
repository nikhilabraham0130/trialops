import { afterEach, describe, expect, it, vi } from "vitest";

import { getStudies } from "./studies";

afterEach(() => vi.unstubAllGlobals());

describe("getStudies", () => {
  it("requests and returns the study catalog", async () => {
    const responseBody = { studies: [] };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getStudies()).resolves.toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/studies",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("rejects unsuccessful API responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    await expect(getStudies()).rejects.toThrow("Study request failed with status 503.");
  });
});
