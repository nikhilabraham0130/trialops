import { useState } from "react";

import { getAuditEvents, type AuditEvent } from "./api/audit";

interface AuditPanelProps {
  entityId: string;
  load?: typeof getAuditEvents;
}

export function AuditPanel({ entityId, load = getAuditEvents }: AuditPanelProps) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setEvents(await load(entityId));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Audit history could not be loaded.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="governance-panel" aria-label="Audit history">
      <div className="workspace-section-heading">
        <div><p className="card-label">Recorded business actions</p><h3>Audit history</h3></div>
        <button className="analysis-button" type="button" disabled={busy}
          onClick={() => void refresh()}>{busy ? "Loading..." : "Load audit history"}</button>
      </div>
      <p className="timing-note">Recent actions for this saved item. Local actions without sign-in use a shared operator label.</p>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {events && <ul className="governance-findings">
        {events.length === 0 && <li>No audit events recorded yet.</li>}
        {events.map((event) => (
          <li key={event.id}>
            <strong>{event.action.replaceAll("_", " ")}</strong>
            <span>{event.actor_id} · {new Date(event.created_at).toLocaleString()}</span>
          </li>
        ))}
      </ul>}
    </section>
  );
}
