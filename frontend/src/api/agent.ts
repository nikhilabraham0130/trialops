import type { AltAbnormalityResponse, SevereAeIncidenceResponse, SubjectSafetySummaryResponse } from "./analytics";

export interface AnalysisPlan {
  id: string;
  question: string;
  dataset_version_id: string;
  purpose: string;
  status: "AWAITING_CONFIRMATION";
  confirmation_required: true;
  tool_call: {
    name: "calculate_alt_gt_3x_uln" | "compare_severe_ae_incidence" | "get_subject_safety_summary";
    arguments: { dataset_version_id: string; subject_id?: string };
  };
}

export interface StoredInterpretation {
  summary: string;
  numeric_claims: { field: string; value: string }[];
  grounding_status: "NUMERICALLY_VERIFIED";
  prompt_version: string;
  model_id: string;
  generated_at: string;
}

export interface AnalysisPlanDetails extends Omit<AnalysisPlan, "status" | "confirmation_required"> {
  status: "AWAITING_CONFIRMATION" | "EXECUTING" | "EXECUTED" | "FAILED";
  confirmation_required: boolean;
  result: AltAbnormalityResponse | SevereAeIncidenceResponse | SubjectSafetySummaryResponse | null;
  interpretation: StoredInterpretation | null;
  created_at: string;
  executed_at: string | null;
}

export interface AnalysisExecution {
  plan_id: string;
  status: "EXECUTED";
  tool_name: "calculate_alt_gt_3x_uln" | "compare_severe_ae_incidence" | "get_subject_safety_summary";
  result: AltAbnormalityResponse | SevereAeIncidenceResponse | SubjectSafetySummaryResponse;
}

export interface GovernanceEvaluation {
  decision: "NOT_READY_FOR_REVIEW" | "REVIEW_REQUIRED" | "APPROVED" | "CHANGES_REQUESTED" | "REJECTED";
  findings: {
    policy_code: "DETERMINISTIC_RESULT_REQUIRED" | "NUMERIC_GROUNDING_REQUIRED" | "INDEPENDENT_REVIEW_REQUIRED";
    status: "PASS" | "FAIL";
    blocking: boolean;
    message: string;
  }[];
}

export interface ReproductionComparison {
  id: string;
  created_at: string;
  plan_id: string;
  dataset_version_id: string;
  tool_name: AnalysisExecution["tool_name"];
  status: "EXACT_MATCH" | "MISMATCH";
  stored_result_sha256: string;
  reproduced_result_sha256: string;
  difference_count: number;
  differences: { path: string; stored: unknown; reproduced: unknown }[];
  differences_truncated: boolean;
}

const apiUrl = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
  });

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    let message = `Request failed with status ${response.status}.`;
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = body.detail;
      if (typeof detail === "object" && detail !== null && "message" in detail &&
          typeof detail.message === "string") {
        message = detail.message;
      } else if (typeof detail === "string") {
        message = detail;
      }
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function createAnalysisPlan(question: string, datasetVersionId: string): Promise<AnalysisPlan> {
  return requestJson("/agent/plans", {
    method: "POST",
    body: JSON.stringify({ question, dataset_version_id: datasetVersionId }),
  });
}

export function getAnalysisPlan(planId: string, signal?: AbortSignal): Promise<AnalysisPlanDetails> {
  return requestJson(`/agent/plans/${encodeURIComponent(planId)}`, { signal });
}

export function getPlanGovernance(planId: string): Promise<GovernanceEvaluation> {
  return requestJson(`/agent/plans/${encodeURIComponent(planId)}/governance`);
}

export function confirmAnalysisPlan(planId: string): Promise<AnalysisExecution> {
  return requestJson(`/agent/plans/${encodeURIComponent(planId)}/confirm`, {
    method: "POST",
    body: JSON.stringify({ confirmed: true }),
  });
}

export function createInterpretation(planId: string): Promise<StoredInterpretation> {
  return requestJson(`/agent/plans/${encodeURIComponent(planId)}/interpretation`, {
    method: "POST",
  });
}

export function reproduceAnalysisPlan(planId: string): Promise<ReproductionComparison> {
  return requestJson(`/agent/plans/${encodeURIComponent(planId)}/reproduce`, { method: "POST" });
}

export function getReproductionHistory(planId: string): Promise<ReproductionComparison[]> {
  return requestJson(`/agent/plans/${encodeURIComponent(planId)}/reproductions`);
}
