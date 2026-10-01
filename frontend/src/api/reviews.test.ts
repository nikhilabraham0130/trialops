import { afterEach, describe, expect, it, vi } from "vitest";

import { decideReview, submitForReview } from "./reviews";

afterEach(() => vi.unstubAllGlobals());

describe("review API", () => {
  it("sends a role token only in the Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state: "PENDING_REVIEW" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await submitForReview("plan-1", "analyst-secret");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/agent/plans/plan-1/submit",
      expect.objectContaining({ method: "POST", headers: expect.objectContaining({ Authorization: "Bearer analyst-secret" }) }),
    );
  });

  it("sends a reviewer decision and its reason", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state: "REJECTED" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await decideReview("plan-1", "reviewer-secret", "REJECTED", " Needs correction. ");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/agent/plans/plan-1/review",
      expect.objectContaining({
        body: '{"action":"REJECTED","comment":"Needs correction."}',
        headers: expect.objectContaining({ Authorization: "Bearer reviewer-secret" }),
      }),
    );
  });
});
