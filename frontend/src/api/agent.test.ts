import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmAnalysisPlan,
  createAnalysisPlan,
  createInterpretation,
  getAnalysisPlan,
  getPlanGovernance,
} from "./agent";

afterEach(() => vi.unstubAllGlobals());

describe("agent API client", () => {
  it("sends only the question and selected dataset when requesting a plan", async () => {
    const responseBody = { id: "plan-1", status: "AWAITING_CONFIRMATION" };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(responseBody), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createAnalysisPlan("Check ALT.", "dataset-1")).resolves.toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/agent/plans",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: "Check ALT.", dataset_version_id: "dataset-1" }),
      }),
    );
  });

  it("requires an explicit true confirmation in the request body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await confirmAnalysisPlan("plan-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/agent/plans/plan-1/confirm",
      expect.objectContaining({ method: "POST", body: '{"confirmed":true}' }),
    );
  });

  it("loads stored plans and requests interpretation through separate endpoints", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    await getAnalysisPlan("plan-1");
    await createInterpretation("plan-1");

    expect(fetchMock).toHaveBeenNthCalledWith(1,
      "http://127.0.0.1:8000/agent/plans/plan-1",
      expect.objectContaining({ signal: undefined }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2,
      "http://127.0.0.1:8000/agent/plans/plan-1/interpretation",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("loads governance from the saved plan's read-only endpoint", async () => {
    const evaluation = { decision: "NOT_READY_FOR_REVIEW", findings: [] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(evaluation), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getPlanGovernance("plan-1")).resolves.toEqual(evaluation);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/agent/plans/plan-1/governance",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("shows a safe backend message when planning cannot reach the model", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: "MODEL_UNAVAILABLE", message: "The planning model is temporarily unavailable." },
    }), { status: 503 })));

    await expect(createAnalysisPlan("Check ALT.", "dataset-1")).rejects.toThrow(
      "The planning model is temporarily unavailable.",
    );
  });

  it("handles plain text and malformed HTTP errors without parsing them as plans", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Interpretation model is unavailable." }), { status: 503 }))
      .mockResolvedValueOnce(new Response("upstream response unavailable", { status: 502 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createInterpretation("plan-1")).rejects.toThrow("Interpretation model is unavailable.");
    await expect(getAnalysisPlan("plan-1")).rejects.toThrow("Request failed with status 502.");
  });
});
