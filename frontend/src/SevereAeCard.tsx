import { useState } from "react";

import {
  getSevereAeIncidence,
  type SevereAeIncidenceResponse,
} from "./api/analytics";

interface SevereAeCardProps {
  datasetVersionId: string;
  loadAnalysis?: typeof getSevereAeIncidence;
}

type AnalysisState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; result: SevereAeIncidenceResponse };

export function SevereAeCard({
  datasetVersionId,
  loadAnalysis = getSevereAeIncidence,
}: SevereAeCardProps) {
  const [state, setState] = useState<AnalysisState>({ status: "idle" });

  async function run() {
    if (state.status === "loading") return;
    setState({ status: "loading" });
    try {
      setState({ status: "loaded", result: await loadAnalysis(datasetVersionId) });
    } catch {
      setState({ status: "error" });
    }
  }

  return (
    <div className="severe-ae-card">
      <button className="analysis-button" type="button" disabled={state.status === "loading"}
        onClick={() => void run()}>
        {state.status === "loading" ? "Calculating severe AEs..." : "Run severe-AE check"}
      </button>
      {state.status === "error" && (
        <p className="inline-error" role="alert">The severe-AE result could not be loaded. Try again.</p>
      )}
      {state.status === "loaded" && <SevereAeResult result={state.result} />}
    </div>
  );
}

export function SevereAeResult({ result }: { result: SevereAeIncidenceResponse }) {
  return (
    <section className="analysis-result" aria-label="Severe AE incidence result">
      <div className="analysis-result-heading">
        <div>
          <p className="card-label">Deterministic result</p>
          <h3>Recorded severe AEs by actual treatment arm</h3>
        </div>
        <span className="method-version">{result.method_version}</span>
      </div>
      <p className="timing-note">{result.population_definition}</p>
      <p className="timing-note">
        {result.excluded_screen_failure_subjects} screen-failure subject(s) excluded from arm denominators.
      </p>
      <div className="table-scroll">
        <table>
          <thead><tr>
            <th>Actual arm</th><th>Subjects</th><th>Subjects with severe AE</th>
            <th>Severe AE events</th><th>Subject incidence</th>
          </tr></thead>
          <tbody>{result.arms.map((arm) => (
            <tr key={arm.arm}>
              <td>{arm.arm}</td>
              <td>{arm.subjects_in_arm}</td>
              <td>{arm.subjects_with_severe_ae}</td>
              <td>{arm.severe_ae_event_count}</td>
              <td>{arm.incidence_percent}%</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="timing-note">{result.timing_limitation}</p>
      <details className="evidence-panel">
        <summary>View severe AE source rows ({result.evidence.length})</summary>
        {result.evidence.length === 0 ? (
          <p>No recorded severe adverse events were found.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Source row</th><th>Subject</th><th>Actual arm</th><th>AE term</th></tr></thead>
              <tbody>{result.evidence.map((event) => (
                <tr key={event.source_record_number}>
                  <td>{event.source_record_number}</td>
                  <td>{event.unique_subject_id}</td>
                  <td>{event.arm}</td>
                  <td>{event.preferred_term}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}
