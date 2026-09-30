import { useState, type FormEvent } from "react";

import {
  getSubjectSafetySummary,
  type SubjectSafetySummaryResponse,
} from "./api/analytics";

interface SubjectSafetyCardProps {
  datasetVersionId: string;
  loadSummary?: typeof getSubjectSafetySummary;
}

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; result: SubjectSafetySummaryResponse };

export function SubjectSafetyCard({
  datasetVersionId,
  loadSummary = getSubjectSafetySummary,
}: SubjectSafetyCardProps) {
  const [subjectId, setSubjectId] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requestedId = subjectId.trim();
    if (!requestedId || state.status === "loading") return;
    setState({ status: "loading" });
    try {
      setState({ status: "loaded", result: await loadSummary(datasetVersionId, requestedId) });
    } catch {
      setState({ status: "error" });
    }
  }

  return (
    <section className="analysis-result" aria-label="Subject safety lookup">
      <div className="analysis-result-heading">
        <div>
          <p className="card-label">Cross-domain source view</p>
          <h3>Subject safety summary</h3>
        </div>
      </div>
      <form className="subject-lookup" onSubmit={(event) => void submit(event)}>
        <label htmlFor={`subject-${datasetVersionId}`}>Unique subject ID (USUBJID)</label>
        <input
          id={`subject-${datasetVersionId}`}
          value={subjectId}
          onChange={(event) => setSubjectId(event.target.value)}
          placeholder="Enter an ID from DM"
          required
        />
        <button className="analysis-button" type="submit" disabled={state.status === "loading"}>
          {state.status === "loading" ? "Loading subject..." : "View subject"}
        </button>
      </form>
      {state.status === "error" && (
        <p className="inline-error" role="alert">
          That subject could not be loaded for this dataset version. Check the ID and try again.
        </p>
      )}
      {state.status === "loaded" && <SubjectSafetyResult result={state.result} />}
    </section>
  );
}

export function SubjectSafetyResult({ result }: { result: SubjectSafetySummaryResponse }) {
  return (
    <div aria-label="Subject safety result">
      <p className="timing-note">
        {result.unique_subject_id} · {result.actual_arm} · {result.age} {result.age_unit} · {result.sex}
      </p>
      <div className="metric-grid">
        <div><strong>{result.ae_event_count}</strong><span>AE events</span></div>
        <div><strong>{result.severe_ae_event_count}</strong><span>severe AE events</span></div>
        <div><strong>{result.serious_ae_event_count}</strong><span>serious AE events</span></div>
        <div><strong>{result.flagged_lab_count}</strong><span>flagged labs of {result.lab_result_count}</span></div>
      </div>
      <p className="timing-note">{result.interpretation_limit}</p>
      <details className="evidence-panel">
        <summary>AE source rows ({result.events.length})</summary>
        <div className="table-scroll"><table>
          <thead><tr><th>Source row</th><th>Term</th><th>Severity</th><th>Serious</th><th>Start date</th></tr></thead>
          <tbody>{result.events.map((event) => (
            <tr key={event.source_record_number}>
              <td>{event.source_record_number}</td><td>{event.preferred_term}</td>
              <td>{event.severity}</td><td>{event.serious_flag}</td><td>{event.start_date_text}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </details>
      <details className="evidence-panel">
        <summary>Flagged LB source rows ({result.flagged_labs.length})</summary>
        <div className="table-scroll"><table>
          <thead><tr><th>Source row</th><th>Test</th><th>Result</th><th>Source flag</th><th>Baseline flag</th></tr></thead>
          <tbody>{result.flagged_labs.map((lab) => (
            <tr key={lab.source_record_number}>
              <td>{lab.source_record_number}</td><td>{lab.test_code}</td>
              <td>{lab.standard_result ?? "—"} {lab.standard_unit ?? ""}</td>
              <td>{lab.range_indicator}</td><td>{lab.baseline_flag ?? "—"}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </details>
    </div>
  );
}
