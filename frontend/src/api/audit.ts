export interface AuditEvent {
  id: string;
  created_at: string;
  actor_id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
}

const apiUrl = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function getAuditEvents(entityId: string): Promise<AuditEvent[]> {
  const response = await fetch(
    `${apiUrl}/audit/events?entity_id=${encodeURIComponent(entityId)}&limit=100`,
    { headers: { Accept: "application/json" } },
  );
  if (!response.ok) throw new Error(`Audit history could not be loaded (${response.status}).`);
  return (await response.json()) as AuditEvent[];
}
