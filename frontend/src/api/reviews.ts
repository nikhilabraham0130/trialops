export type ReviewState = "DRAFT" | "PENDING_REVIEW" | "APPROVED" | "CHANGES_REQUESTED" | "REJECTED";
export type ReviewDecision = "APPROVED" | "CHANGES_REQUESTED" | "REJECTED";

export interface ReviewStatus {
  plan_id: string;
  state: ReviewState;
  submitted_by: string | null;
  submitted_at: string | null;
  history: {
    id: string;
    action: "SUBMITTED" | ReviewDecision;
    actor_id: string;
    comment: string | null;
    created_at: string;
  }[];
}

const apiUrl = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

async function requestReview(path: string, init?: RequestInit): Promise<ReviewStatus> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    if (typeof body === "object" && body !== null && "detail" in body &&
        typeof body.detail === "object" && body.detail !== null &&
        "message" in body.detail && typeof body.detail.message === "string") {
      throw new Error(body.detail.message);
    }
    throw new Error(`Review request failed with status ${response.status}.`);
  }
  return (await response.json()) as ReviewStatus;
}

export function getReviewStatus(planId: string): Promise<ReviewStatus> {
  return requestReview(`/agent/plans/${encodeURIComponent(planId)}/review`);
}

export function submitForReview(planId: string, token: string): Promise<ReviewStatus> {
  return requestReview(`/agent/plans/${encodeURIComponent(planId)}/submit`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  });
}

export function decideReview(
  planId: string, token: string, action: ReviewDecision, comment: string,
): Promise<ReviewStatus> {
  return requestReview(`/agent/plans/${encodeURIComponent(planId)}/review`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ action, comment: comment.trim() || null }),
  });
}
