import { afterEach, describe, expect, it, vi } from "vitest";

import { getAltAbnormalities } from "./analytics";

afterEach(() => vi.unstubAllGlobals());

describe("getAltAbnormalities", () => {
  it("requests the selected dataset version's deterministic ALT result", async () => {
    const responseBody = {
      dataset_version_id: "version-1",
      method_version: "alt-gt-3x-uln/1.0",
      threshold_multiplier: "3",
      alt_row_count: 10,
      eligible_row_count: 10,
      excluded_row_count: 0,
      qualifying_measurement_count: 1,
      subjects_with_qualifying_measurement: 1,
      exceedances: [],
      findings: [],
      timing_limitation: "Timing is not established.",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getAltAbnormalities("version-1")).resolves.toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/dataset-versions/version-1/analytics/alt-gt-3x-uln",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("rejects an unsuccessful analytics response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));

    await expect(getAltAbnormalities("missing-version")).rejects.toThrow(
      "ALT analytics request failed with status 404.",
    );
  });
});
