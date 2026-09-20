export type FindingSeverity = "WARNING" | "BLOCKING";

export type TimingClassification = "BASELINE" | "NOT_IDENTIFIED_AS_BASELINE";

export interface ValidationFinding {
  rule_code: string;
  severity: FindingSeverity;
  domain: string;
  source_record_number: number | null;
  message: string;
}

export interface AltExceedance {
  source_record_number: number;
  unique_subject_id: string;
  standard_result: string;
  upper_reference_limit: string;
  threshold: string;
  timing: TimingClassification;
}

export interface AltAbnormalityResponse {
  dataset_version_id: string;
  method_version: string;
  threshold_multiplier: string;
  alt_row_count: number;
  eligible_row_count: number;
  excluded_row_count: number;
  qualifying_measurement_count: number;
  subjects_with_qualifying_measurement: number;
  exceedances: AltExceedance[];
  findings: ValidationFinding[];
  timing_limitation: string;
}

const apiUrl = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function getAltAbnormalities(
  datasetVersionId: string,
  signal?: AbortSignal,
): Promise<AltAbnormalityResponse> {
  const response = await fetch(
    `${apiUrl}/dataset-versions/${datasetVersionId}/analytics/alt-gt-3x-uln`,
    {
      headers: { Accept: "application/json" },
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(`ALT analytics request failed with status ${response.status}.`);
  }

  return (await response.json()) as AltAbnormalityResponse;
}
