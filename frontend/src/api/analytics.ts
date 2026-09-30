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

export interface SevereAeIncidenceResponse {
  dataset_version_id: string;
  method_version: string;
  excluded_screen_failure_subjects: number;
  population_definition: string;
  timing_limitation: string;
  arms: {
    arm: string;
    subjects_in_arm: number;
    subjects_with_severe_ae: number;
    severe_ae_event_count: number;
    incidence_percent: string;
  }[];
  evidence: {
    source_record_number: number;
    unique_subject_id: string;
    arm: string;
    preferred_term: string;
  }[];
}

export interface SubjectSafetySummaryResponse {
  dataset_version_id: string;
  method_version: string;
  unique_subject_id: string;
  actual_arm: string;
  age: number;
  age_unit: string;
  sex: string;
  ae_event_count: number;
  severe_ae_event_count: number;
  serious_ae_event_count: number;
  lab_result_count: number;
  flagged_lab_count: number;
  events: {
    source_record_number: number;
    preferred_term: string;
    severity: string;
    serious_flag: string;
    start_date_text: string;
  }[];
  flagged_labs: {
    source_record_number: number;
    test_code: string;
    standard_result: string | null;
    standard_unit: string | null;
    lower_reference_limit: string | null;
    upper_reference_limit: string | null;
    range_indicator: string;
    baseline_flag: string | null;
    observed_at_text: string;
  }[];
  interpretation_limit: string;
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

export async function getSevereAeIncidence(
  datasetVersionId: string,
  signal?: AbortSignal,
): Promise<SevereAeIncidenceResponse> {
  const response = await fetch(
    `${apiUrl}/dataset-versions/${encodeURIComponent(datasetVersionId)}/analytics/severe-ae-incidence`,
    { headers: { Accept: "application/json" }, signal },
  );
  if (!response.ok) {
    throw new Error(`Severe-AE analytics request failed with status ${response.status}.`);
  }
  return (await response.json()) as SevereAeIncidenceResponse;
}

export async function getSubjectSafetySummary(
  datasetVersionId: string,
  uniqueSubjectId: string,
  signal?: AbortSignal,
): Promise<SubjectSafetySummaryResponse> {
  const response = await fetch(
    `${apiUrl}/dataset-versions/${encodeURIComponent(datasetVersionId)}/analytics/subjects/${encodeURIComponent(uniqueSubjectId)}/safety-summary`,
    { headers: { Accept: "application/json" }, signal },
  );
  if (!response.ok) {
    throw new Error(`Subject safety request failed with status ${response.status}.`);
  }
  return (await response.json()) as SubjectSafetySummaryResponse;
}
