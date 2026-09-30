import { afterEach, describe, expect, it, vi } from "vitest";

import { getAltAbnormalities, getSevereAeIncidence, getSubjectSafetySummary } from "./analytics";

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

describe("getSevereAeIncidence", () => {
  it("requests a version-specific severe-AE result", async () => {
    const body = { dataset_version_id: "version-1", arms: [], evidence: [] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getSevereAeIncidence("version-1")).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/dataset-versions/version-1/analytics/severe-ae-incidence",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("rejects a failed severe-AE response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
    await expect(getSevereAeIncidence("missing")).rejects.toThrow(
      "Severe-AE analytics request failed with status 404.",
    );
  });
});

describe("getSubjectSafetySummary", () => {
  it("encodes the selected subject within the selected version URL", async () => {
    const body = { unique_subject_id: "S/1", events: [], flagged_labs: [] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getSubjectSafetySummary("version-1", "S/1")).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/dataset-versions/version-1/analytics/subjects/S%2F1/safety-summary",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("rejects a subject that the API cannot load", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
    await expect(getSubjectSafetySummary("version-1", "missing")).rejects.toThrow(
      "Subject safety request failed with status 404.",
    );
  });
});
