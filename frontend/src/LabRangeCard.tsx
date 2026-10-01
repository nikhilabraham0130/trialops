import { useState, type FormEvent } from "react";

import { getLabReferenceRange, type LabRangeResponse } from "./api/analytics";

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; result: LabRangeResponse };

export function LabRangeCard({
  datasetVersionId,
  loadAnalysis = getLabReferenceRange,
}: {
  datasetVersionId: string;
  loadAnalysis?: typeof getLabReferenceRange;
}) {
  const [testCode, setTestCode] = useState("AST");
  const [state, setState] = useState<State>({ status: "idle" });

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.status === "loading" || !/^[A-Z][A-Z0-9]{1,7}$/.test(testCode)) return;
    setState({ status: "loading" });
    try {
      setState({ status: "loaded", result: await loadAnalysis(datasetVersionId, testCode) });
    } catch {
      setState({ status: "error" });
    }
  }

  return (
    <div className="lab-range-card">
      <form onSubmit={(event) => void run(event)}>
        <label htmlFor={`lab-code-${datasetVersionId}`}>Lab test code (LBTESTCD)</label>
        <input id={`lab-code-${datasetVersionId}`} value={testCode} maxLength={8}
          disabled={state.status === "loading"}
          onChange={(event) => {
            setTestCode(event.target.value.toUpperCase());
            setState({ status: "idle" });
          }} />
        <button className="analysis-button" type="submit" disabled={state.status === "loading" || !/^[A-Z][A-Z0-9]{1,7}$/.test(testCode)}>
          {state.status === "loading" ? "Checking lab range..." : "Check lab reference range"}
        </button>
      </form>
      <p className="timing-note">Use a dataset lab test code such as AST, BILI, or WBC.</p>
      {state.status === "error" && <p className="inline-error" role="alert">The lab result could not be loaded. Check the test code and try again.</p>}
      {state.status === "loaded" && <LabRangeResult result={state.result} />}
    </div>
  );
}

export function LabRangeResult({ result }: { result: LabRangeResponse }) {
  return (
    <section className="analysis-result" aria-label="Lab reference range result">
      <div className="analysis-result-heading">
        <div>
          <p className="card-label">Deterministic result</p>
          <h3>{result.test_code} results outside supplied reference limits</h3>
        </div>
        <span className="method-version">{result.method_version}</span>
      </div>
      <p>{result.out_of_range_rows} of {result.eligible_rows} eligible measurements were outside their row-specific limits ({result.below_lower_rows} below, {result.above_upper_rows} above). {result.subjects_with_out_of_range} distinct subject(s) had an out-of-range result.</p>
      <p className="timing-note">{result.excluded_rows} of {result.total_rows} rows excluded for missing or invalid numeric values or limits.</p>
      <p className="timing-note">{result.interpretation_limit}</p>
      <details className="evidence-panel">
        <summary>View out-of-range source rows ({result.evidence.length}{result.evidence_truncated ? "+" : ""})</summary>
        {result.evidence_truncated && <p>Showing the first {result.evidence.length} rows; counts include all qualifying rows.</p>}
        {result.evidence.length === 0 ? <p>No out-of-range rows were found.</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Source row</th><th>Subject</th><th>Result</th><th>Lower</th><th>Upper</th><th>Direction</th><th>Baseline flag</th></tr></thead>
              <tbody>{result.evidence.map((item) => (
                <tr key={item.source_record_number}>
                  <td>{item.source_record_number}</td>
                  <td>{item.unique_subject_id}</td>
                  <td>{item.standard_result} {item.standard_unit ?? ""}</td>
                  <td>{item.lower_reference_limit}</td>
                  <td>{item.upper_reference_limit}</td>
                  <td>{item.direction.replaceAll("_", " ")}</td>
                  <td>{item.baseline_flag ?? "not flagged"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}
