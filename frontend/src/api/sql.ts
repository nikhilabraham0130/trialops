export interface GovernedSQLResult {
  dataset_version_id: string;
  validated_sql: string;
  row_count: number;
  row_limit: number;
  rows: Record<string, unknown>[];
}

const apiUrl = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function runGovernedSQL(
  datasetVersionId: string,
  candidateSql: string,
): Promise<GovernedSQLResult> {
  const response = await fetch(
    `${apiUrl}/dataset-versions/${encodeURIComponent(datasetVersionId)}/sql`,
    {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_sql: candidateSql }),
    },
  );
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    if (typeof body === "object" && body !== null && "detail" in body &&
        typeof body.detail === "object" && body.detail !== null &&
        "message" in body.detail && typeof body.detail.message === "string") {
      throw new Error(body.detail.message);
    }
    throw new Error(`SQL request failed with status ${response.status}.`);
  }
  return (await response.json()) as GovernedSQLResult;
}
