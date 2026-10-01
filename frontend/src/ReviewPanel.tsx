import { useState } from "react";

import {
  decideReview, getReviewStatus, submitForReview,
  type ReviewDecision, type ReviewStatus,
} from "./api/reviews";

interface ReviewPanelProps {
  planId: string;
  readyToSubmit: boolean;
  onChanged?: () => void;
  load?: typeof getReviewStatus;
  submit?: typeof submitForReview;
  decide?: typeof decideReview;
}

export function ReviewPanel({
  planId, readyToSubmit, onChanged, load = getReviewStatus,
  submit = submitForReview, decide = decideReview,
}: ReviewPanelProps) {
  const [review, setReview] = useState<ReviewStatus | null>(null);
  const [token, setToken] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setReview(await load(planId));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Review could not be loaded.");
    } finally {
      setBusy(false);
    }
  }

  async function takeAction(action: ReviewDecision | "SUBMITTED") {
    if (!token.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated = action === "SUBMITTED"
        ? await submit(planId, token.trim())
        : await decide(planId, token.trim(), action, comment);
      setReview(updated);
      setToken("");
      setComment("");
      onChanged?.();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Review action failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="governance-panel" aria-label="Independent review">
      <p className="card-label">Server-enforced decision</p>
      <h3>Independent review</h3>
      <button className="analysis-button" type="button" disabled={busy}
        onClick={() => void refresh()}>Load review status</button>
      {review && <p className="timing-note">State: <strong>{review.state.replaceAll("_", " ")}</strong></p>}
      <p className="timing-note">
        Use the local analyst token to submit, then a different reviewer token to decide.
        The token stays in this form only and is cleared after a successful action.
      </p>
      {review && <>
        <label className="review-label" htmlFor={`review-token-${planId}`}>Local role token</label>
        <input id={`review-token-${planId}`} type="password" autoComplete="off"
          value={token} onChange={(event) => setToken(event.target.value)} />
      </>}
      {review?.state === "DRAFT" && (
        <button className="analysis-button" type="button" disabled={busy || !readyToSubmit || !token.trim()}
          onClick={() => void takeAction("SUBMITTED")}>Submit for review</button>
      )}
      {review?.state === "PENDING_REVIEW" && (
        <>
          <label className="review-label" htmlFor={`review-comment-${planId}`}>Reviewer comment</label>
          <textarea id={`review-comment-${planId}`} rows={2} maxLength={2000}
            value={comment} onChange={(event) => setComment(event.target.value)} />
          <div className="review-actions">
            <button className="analysis-button" type="button" disabled={busy || !token.trim()}
              onClick={() => void takeAction("APPROVED")}>Approve</button>
            <button className="analysis-button" type="button" disabled={busy || !token.trim() || !comment.trim()}
              onClick={() => void takeAction("CHANGES_REQUESTED")}>Request changes</button>
            <button className="analysis-button" type="button" disabled={busy || !token.trim() || !comment.trim()}
              onClick={() => void takeAction("REJECTED")}>Reject</button>
          </div>
        </>
      )}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {review && <ul className="governance-findings" aria-label="Review history">
        {review.history.length === 0 && <li>No review actions yet.</li>}
        {review.history.map((event) => (
          <li key={event.id}>
            <strong>{event.action.replaceAll("_", " ")}</strong>
            <span>{event.actor_id} · {new Date(event.created_at).toLocaleString()}
              {event.comment ? ` · ${event.comment}` : ""}</span>
          </li>
        ))}
      </ul>}
    </section>
  );
}
