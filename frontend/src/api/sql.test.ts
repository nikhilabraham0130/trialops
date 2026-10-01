import { afterEach, describe, expect, it, vi } from "vitest";

import { runGovernedSQL } from "./sql";

afterEach(() => vi.unstubAllGlobals());

describe("runGovernedSQL", () => {
  it("sends a candidate query for one dataset version", async () => {
    const body = { validated_sql: "SELECT * FROM vw_subjects LIMIT 100", row_count: 0, rows: [] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(runGovernedSQL("version-1", "SELECT * FROM vw_subjects")).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/dataset-versions/version-1/sql",
      expect.objectContaining({
        method: "POST",
        body: '{"candidate_sql":"SELECT * FROM vw_subjects"}',
      }),
    );
  });

  it("shows the backend's safe policy message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: "SQL_POLICY_VIOLATION", message: "Only one SELECT is permitted." },
    }), { status: 422 })));
    await expect(runGovernedSQL("version-1", "DROP TABLE dm_subject")).rejects.toThrow(
      "Only one SELECT is permitted.",
    );
  });
});
