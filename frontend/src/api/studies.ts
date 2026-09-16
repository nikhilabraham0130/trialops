export interface DatasetVersionSummary {
  id: string;
  version_label: string;
  status: "RECEIVED" | "VALIDATING" | "VALID" | "VALID_WITH_WARNINGS" | "BLOCKED";
  subject_count: number;
}

export interface StudySummary {
  id: string;
  study_oid: string;
  title: string | null;
  dataset_versions: DatasetVersionSummary[];
}

export interface StudyListResponse {
  studies: StudySummary[];
}

const apiUrl = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function getStudies(signal?: AbortSignal): Promise<StudyListResponse> {
  const response = await fetch(`${apiUrl}/studies`, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Study request failed with status ${response.status}.`);
  }

  return (await response.json()) as StudyListResponse;
}
