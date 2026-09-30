import { useEffect, useState, type FormEvent } from "react";

import {
  confirmAnalysisPlan,
  createAnalysisPlan,
  createInterpretation,
  getAnalysisPlan,
  getPlanGovernance,
  type AnalysisPlan,
  type AnalysisPlanDetails,
  type GovernanceEvaluation,
  type StoredInterpretation,
} from "./api/agent";
import type { AltAbnormalityResponse } from "./api/analytics";
import type { DatasetVersionSummary, StudyListResponse } from "./api/studies";
import { SevereAeResult } from "./SevereAeCard";

type PlanView = Omit<AnalysisPlanDetails, "created_at" | "executed_at">;
type WorkflowStep = "idle" | "loading" | "planning" | "executing" | "interpreting" | "governing";

interface AnalysisWorkspaceProps {
  studies: StudyListResponse["studies"];
  createPlan?: typeof createAnalysisPlan;
  loadPlan?: typeof getAnalysisPlan;
  confirmPlan?: typeof confirmAnalysisPlan;
  interpretPlan?: typeof createInterpretation;
  loadGovernance?: typeof getPlanGovernance;
}

function toPlanView(plan: AnalysisPlan): PlanView {
  return { ...plan, result: null, interpretation: null };
}

function setPlanUrl(planId: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set("plan", planId);
  window.history.replaceState(null, "", url);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function ResultPanel({ result }: { result: AltAbnormalityResponse }) {
  return (
    <section className="workspace-result" aria-labelledby="workspace-result-title">
      <div className="workspace-section-heading">
        <div>
          <p className="card-label">Trusted Python calculation</p>
          <h3 id="workspace-result-title">ALT above 3 × upper limit of normal</h3>
        </div>
        <span className="method-version">{result.method_version}</span>
      </div>
      <div className="metric-grid">
        <div><strong>{result.eligible_row_count}</strong><span>eligible ALT measurements</span></div>
        <div><strong>{result.qualifying_measurement_count}</strong><span>measurements above threshold</span></div>
        <div><strong>{result.subjects_with_qualifying_measurement}</strong><span>distinct subjects</span></div>
      </div>
      <p className="timing-note"><strong>Timing limitation:</strong> {result.timing_limitation}</p>
      {result.findings.length > 0 && (
        <div className="validation-findings">
          <strong>{result.excluded_row_count} excluded measurement(s)</strong>
          <ul>{result.findings.map((finding) => (
            <li key={`${finding.rule_code}-${finding.source_record_number ?? "all"}`}>
              {finding.message}
            </li>
          ))}</ul>
        </div>
      )}
      <details className="evidence-panel">
        <summary>View source evidence ({result.exceedances.length})</summary>
        {result.exceedances.length === 0 ? (
          <p>No measurements exceeded the threshold.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Source row</th><th>Subject</th><th>ALT result</th><th>Upper limit</th><th>Threshold</th><th>Timing</th></tr></thead>
              <tbody>{result.exceedances.map((item) => (
                <tr key={item.source_record_number}>
                  <td>{item.source_record_number}</td>
                  <td>{item.unique_subject_id}</td>
                  <td>{item.standard_result}</td>
                  <td>{item.upper_reference_limit}</td>
                  <td>{item.threshold}</td>
                  <td>{item.timing.replaceAll("_", " ")}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}

function InterpretationPanel({ interpretation }: { interpretation: StoredInterpretation }) {
  return (
    <section className="interpretation-panel" aria-labelledby="interpretation-title">
      <p className="card-label">AI explanation · numerically verified</p>
      <h3 id="interpretation-title">Interpretation</h3>
      <p>{interpretation.summary}</p>
      <p className="interpretation-footnote">
        Numeric claims checked against the stored result. This explanation has not received independent clinical review.
      </p>
    </section>
  );
}

export function AnalysisWorkspace({
  studies,
  createPlan = createAnalysisPlan,
  loadPlan = getAnalysisPlan,
  confirmPlan = confirmAnalysisPlan,
  interpretPlan = createInterpretation,
  loadGovernance = getPlanGovernance,
}: AnalysisWorkspaceProps) {
  const versions: DatasetVersionSummary[] = studies.flatMap((study) => study.dataset_versions);
  const [chosenVersionId, setChosenVersionId] = useState("");
  const selectedVersionId = chosenVersionId || versions[0]?.id || "";
  const [question, setQuestion] = useState("");
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [step, setStep] = useState<WorkflowStep>("idle");
  const [error, setError] = useState<string | null>(null);
  const [governance, setGovernance] = useState<GovernanceEvaluation | null>(null);

  useEffect(() => {
    const planId = new URLSearchParams(window.location.search).get("plan");
    if (!planId) return;

    const controller = new AbortController();
    setStep("loading");
    void loadPlan(planId, controller.signal)
      .then((saved) => {
        if (controller.signal.aborted) return;
        setPlan(saved);
        setQuestion(saved.question);
        setChosenVersionId(saved.dataset_version_id);
        setGovernance(null);
        setError(null);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted && !(failure instanceof DOMException && failure.name === "AbortError")) {
          setError(`Saved analysis could not be loaded: ${errorMessage(failure)}`);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setStep("idle");
      });

    return () => controller.abort();
  }, [loadPlan]);

  async function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || !selectedVersionId || step !== "idle") return;
    setStep("planning");
    setError(null);
    try {
      const created = await createPlan(question.trim(), selectedVersionId);
      setPlan(toPlanView(created));
      setGovernance(null);
      setPlanUrl(created.id);
    } catch (failure) {
      setError(`Plan could not be created: ${errorMessage(failure)}`);
    } finally {
      setStep("idle");
    }
  }

  async function execute() {
    if (!plan || plan.status !== "AWAITING_CONFIRMATION" || step !== "idle") return;
    setStep("executing");
    setError(null);
    try {
      const execution = await confirmPlan(plan.id);
      setGovernance(null);
      setPlan((current) => current?.id === plan.id ? {
        ...current,
        status: execution.status,
        confirmation_required: false,
        result: execution.result,
      } : current);
    } catch (failure) {
      setError(`Analysis could not be executed: ${errorMessage(failure)}`);
    } finally {
      setStep("idle");
    }
  }

  async function explain() {
    if (!plan || plan.status !== "EXECUTED" || plan.interpretation || step !== "idle") return;
    setStep("interpreting");
    setError(null);
    try {
      const interpretation = await interpretPlan(plan.id);
      setGovernance(null);
      setPlan((current) => current?.id === plan.id ? { ...current, interpretation } : current);
    } catch (failure) {
      setError(`Interpretation could not be created: ${errorMessage(failure)}`);
    } finally {
      setStep("idle");
    }
  }

  async function checkGovernance() {
    if (!plan || step !== "idle") return;
    setStep("governing");
    setError(null);
    try {
      setGovernance(await loadGovernance(plan.id));
    } catch (failure) {
      setError(`Governance checks could not be loaded: ${errorMessage(failure)}`);
    } finally {
      setStep("idle");
    }
  }

  const busy = step !== "idle";
  return (
    <section className="workspace" aria-labelledby="workspace-title">
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">Analysis workspace</p>
          <h2 id="workspace-title">Ask a safety question</h2>
          <p>Review the proposed analysis before trusted Python code calculates a result.</p>
        </div>
        <span className="workspace-stage">{plan ? plan.status.replaceAll("_", " ") : "NEW ANALYSIS"}</span>
      </div>

      <form className="question-form" onSubmit={(event) => void propose(event)}>
        <label htmlFor="dataset-version">Dataset version</label>
        <select id="dataset-version" value={selectedVersionId} disabled={busy || versions.length === 0}
          onChange={(event) => setChosenVersionId(event.target.value)}>
          {versions.map((version) => (
            <option key={version.id} value={version.id}>{version.version_label} · {version.subject_count} subjects</option>
          ))}
        </select>
        <label htmlFor="safety-question">Your question</label>
        <textarea id="safety-question" rows={3} maxLength={2000} value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Were any ALT measurements elevated, or which arm had severe AEs?" />
        <div className="form-footer">
          <span>Supports ALT above 3 × ULN and recorded severe AEs by actual arm.</span>
          <button className="analysis-button" type="submit" disabled={busy || !question.trim() || !selectedVersionId}>
            {step === "planning" ? "Preparing plan..." : "Propose analysis"}
          </button>
        </div>
      </form>

      {step === "loading" && <p className="workspace-progress" role="status">Loading saved analysis...</p>}
      {error && <div className="inline-error workspace-error" role="alert">{error}</div>}

      {plan && (
        <div className="plan-stack">
          <section className="plan-panel" aria-labelledby="plan-title">
            <div className="workspace-section-heading">
              <div>
                <p className="card-label">Proposed tool</p>
                <h3 id="plan-title">
                  {plan.tool_call.name === "calculate_alt_gt_3x_uln"
                    ? "ALT threshold calculation"
                    : "Severe AE incidence by arm"}
                </h3>
              </div>
              <span className="method-version">{plan.tool_call.name}</span>
            </div>
            <p><strong>Question:</strong> {plan.question}</p>
            <p><strong>Purpose:</strong> {plan.purpose}</p>
            <p className="plan-id">Saved analysis ID: <code>{plan.id}</code></p>
            {plan.status === "AWAITING_CONFIRMATION" && (
              <div className="confirmation-row">
                <p>No calculation has run yet. Confirm this saved plan to calculate the result.</p>
                <button className="analysis-button" type="button" disabled={busy} onClick={() => void execute()}>
                  {step === "executing" ? "Calculating..." : "Confirm and calculate"}
                </button>
              </div>
            )}
          </section>

          {plan.result && ("arms" in plan.result
            ? <SevereAeResult result={plan.result} />
            : <ResultPanel result={plan.result} />)}

          {plan.status === "EXECUTED" && plan.result && !plan.interpretation && (
            <div className="explanation-action">
              <p>The calculation is stored. Ask AI to explain its aggregate result.</p>
              <button className="analysis-button" type="button" disabled={busy} onClick={() => void explain()}>
                {step === "interpreting" ? "Verifying explanation..." : "Generate explanation"}
              </button>
            </div>
          )}
          {plan.interpretation && <InterpretationPanel interpretation={plan.interpretation} />}

          <section className="governance-panel" aria-labelledby="governance-title">
            <div className="workspace-section-heading">
              <div>
                <p className="card-label">Deterministic policy checks</p>
                <h3 id="governance-title">Governance</h3>
              </div>
              <button className="analysis-button" type="button" disabled={busy}
                onClick={() => void checkGovernance()}>
                {step === "governing" ? "Checking..." : "Check current status"}
              </button>
            </div>
            {governance ? (
              <>
                <p className="governance-decision">
                  {governance.decision === "REVIEW_REQUIRED"
                    ? "Ready for independent review, but not approved."
                    : "Not ready for independent review."}
                </p>
                <ul className="governance-findings">{governance.findings.map((finding) => (
                  <li key={finding.policy_code}>
                    <strong className={finding.status === "PASS" ? "policy-pass" : "policy-fail"}>
                      {finding.status}
                    </strong>
                    <span>{finding.message}</span>
                  </li>
                ))}</ul>
              </>
            ) : <p>Check the saved plan against the backend rules for calculation, grounding, and review.</p>}
            <p className="governance-note">Independent review is not available in this demo yet.</p>
          </section>
        </div>
      )}
    </section>
  );
}
