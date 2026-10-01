import { useState, type FormEvent } from "react";

import { proposeClinicalSQL, runGovernedSQL, type GovernedSQLResult, type SQLProposal } from "./api/sql";
import { AuditPanel } from "./AuditPanel";

const starterQuery = "SELECT actual_arm, COUNT(*) AS subjects FROM vw_subjects GROUP BY actual_arm";

interface SQLWorkbenchProps {
  datasetVersionId: string;
  execute?: typeof runGovernedSQL;
  propose?: typeof proposeClinicalSQL;
}

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; result: GovernedSQLResult };

export function SQLWorkbench({
  datasetVersionId, execute = runGovernedSQL, propose = proposeClinicalSQL,
}: SQLWorkbenchProps) {
  const [sql, setSql] = useState(starterQuery);
  const [state, setState] = useState<State>({ status: "idle" });
  const [question, setQuestion] = useState("");
  const [proposal, setProposal] = useState<SQLProposal | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [proposing, setProposing] = useState(false);

  async function draft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || proposing) return;
    setProposing(true);
    setProposal(null);
    setProposalError(null);
    setState({ status: "idle" });
    try {
      const next = await propose(datasetVersionId, question.trim());
      setProposal(next);
      setSql(next.validated_sql);
    } catch (error) {
      setProposalError(error instanceof Error ? error.message : "Could not draft SQL.");
    } finally {
      setProposing(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sql.trim() || state.status === "loading") return;
    setState({ status: "loading" });
    try {
      setState({ status: "loaded", result: await execute(datasetVersionId, sql.trim()) });
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "The query could not be completed.",
      });
    }
  }

  const result = state.status === "loaded" ? state.result : null;
  const columns = result?.rows[0] ? Object.keys(result.rows[0]) : [];

  return (
    <section className="analysis-result" aria-label="Governed SQL workbench">
      <div className="analysis-result-heading">
        <div>
          <p className="card-label">Read-only clinical query</p>
          <h3>Governed SQL workbench</h3>
        </div>
      </div>
      <p className="timing-note">
        Query one curated view: vw_subjects, vw_adverse_events, or vw_laboratory_results.
        The selected dataset version, database permissions, timeout, and 100-row cap are enforced by the backend.
      </p>
      <form className="sql-form" onSubmit={(event) => void draft(event)}>
        <label htmlFor={`sql-question-${datasetVersionId}`}>Ask for a clinical query</label>
        <textarea id={`sql-question-${datasetVersionId}`} rows={2} maxLength={2000}
          value={question} onChange={(event) => setQuestion(event.target.value)} required />
        <button className="analysis-button" type="submit" disabled={proposing}>
          {proposing ? "Drafting SQL..." : "Draft SQL with AI"}
        </button>
      </form>
      {proposalError && <p className="inline-error" role="alert">{proposalError}</p>}
      {proposal && <p className="timing-note" aria-label="SQL proposal">
        <strong>Proposed, not run:</strong> {proposal.purpose} Review the query below, then run it explicitly.
      </p>}
      <form className="sql-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor={`sql-${datasetVersionId}`}>SQL query</label>
        <textarea id={`sql-${datasetVersionId}`} rows={3} maxLength={4000}
          value={sql} onChange={(event) => {
            setSql(event.target.value);
            setProposal(null);
            setState({ status: "idle" });
          }} required />
        <button className="analysis-button" type="submit" disabled={state.status === "loading"}>
          {state.status === "loading" ? "Validating query..." : "Run read-only query"}
        </button>
      </form>
      {state.status === "error" && <p className="inline-error" role="alert">{state.message}</p>}
      {result && (
        <div aria-label="Governed SQL result">
          <p className="timing-note">{result.row_count} row(s) returned; maximum {result.row_limit}.</p>
          <p className="timing-note"><strong>Executed SQL:</strong> <code>{result.validated_sql}</code></p>
          {result.rows.length === 0 ? <p>No rows matched this query.</p> : (
            <div className="table-scroll"><table>
              <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
              <tbody>{result.rows.map((row, index) => (
                <tr key={index}>{columns.map((column) => (
                  <td key={column}>{row[column] === null ? "—" : String(row[column])}</td>
                ))}</tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      )}
      <AuditPanel entityId={datasetVersionId} />
    </section>
  );
}
