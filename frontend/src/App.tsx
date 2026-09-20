import { useEffect, useState } from "react";

import {
  getAltAbnormalities,
  type AltAbnormalityResponse,
} from "./api/analytics";
import { getStudies, type StudyListResponse } from "./api/studies";
import "./styles.css";

type LoadStudies = (signal?: AbortSignal) => Promise<StudyListResponse>;
type LoadAltAnalysis = (
  datasetVersionId: string,
  signal?: AbortSignal,
) => Promise<AltAbnormalityResponse>;

type StudyState =
  | { status: "loading" }
  | { status: "loaded"; response: StudyListResponse }
  | { status: "error" };

interface AppProps {
  loadStudies?: LoadStudies;
  loadAltAnalysis?: LoadAltAnalysis;
}

type AltAnalysisState =
  | { status: "loading" }
  | { status: "loaded"; response: AltAbnormalityResponse }
  | { status: "error" };

export function App({
  loadStudies = getStudies,
  loadAltAnalysis = getAltAbnormalities,
}: AppProps) {
  const [state, setState] = useState<StudyState>({ status: "loading" });
  const [altAnalyses, setAltAnalyses] = useState<Record<string, AltAnalysisState>>({});

  useEffect(() => {
    const controller = new AbortController();

    void loadStudies(controller.signal)
      .then((response) => setState({ status: "loaded", response }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState({ status: "error" });
        }
      });

    return () => controller.abort();
  }, [loadStudies]);

  const runAltAnalysis = (datasetVersionId: string) => {
    setAltAnalyses((current) => ({
      ...current,
      [datasetVersionId]: { status: "loading" },
    }));
    void loadAltAnalysis(datasetVersionId)
      .then((response) =>
        setAltAnalyses((current) => ({
          ...current,
          [datasetVersionId]: { status: "loaded", response },
        })),
      )
      .catch(() =>
        setAltAnalyses((current) => ({
          ...current,
          [datasetVersionId]: { status: "error" },
        })),
      );
  };

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="TrialOps home">
          <span className="brand-mark" aria-hidden="true">
            T
          </span>
          <span>TrialOps</span>
        </a>
        <span className="environment-badge">Local workspace</span>
      </header>

      <main>
        <section className="hero" aria-labelledby="page-title">
          <p className="eyebrow">Controlled data foundation</p>
          <h1 id="page-title">Study overview</h1>
          <p className="hero-copy">
            Review the dataset versions registered in TrialOps and the normalized subjects
            available for governed analysis.
          </p>
        </section>

        <section className="content" aria-live="polite">
          {state.status === "loading" && (
            <div className="state-panel">
              <span className="spinner" aria-hidden="true" />
              <p>Loading registered studies…</p>
            </div>
          )}

          {state.status === "error" && (
            <div className="state-panel error-panel" role="alert">
              <p className="state-title">The study catalog could not be loaded.</p>
              <p>Confirm that FastAPI is running on the configured API address, then refresh.</p>
            </div>
          )}

          {state.status === "loaded" && state.response.studies.length === 0 && (
            <div className="state-panel">
              <p className="state-title">No studies are registered yet.</p>
              <p>Import and validate a dataset to begin the controlled analysis workflow.</p>
            </div>
          )}

          {state.status === "loaded" && state.response.studies.length > 0 && (
            <div className="study-grid">
              {state.response.studies.map((study) => (
                <article className="study-card" key={study.id}>
                  <div className="study-heading">
                    <div>
                      <p className="card-label">Study</p>
                      <h2>{study.title ?? study.study_oid}</h2>
                      {study.title && <p className="study-oid">{study.study_oid}</p>}
                    </div>
                    <span className="version-count">
                      {study.dataset_versions.length} dataset version
                      {study.dataset_versions.length === 1 ? "" : "s"}
                    </span>
                  </div>

                  <div className="version-list">
                    {study.dataset_versions.map((version) => {
                      const altState = altAnalyses[version.id];
                      return (
                        <div className="version-block" key={version.id}>
                          <div className="version-row">
                            <div>
                              <p className="version-label">{version.version_label}</p>
                              <span className={`status status-${version.status.toLowerCase()}`}>
                                {version.status.replaceAll("_", " ")}
                              </span>
                            </div>
                            <div className="version-actions">
                              <div className="subject-total">
                                <strong>{version.subject_count.toLocaleString()}</strong>
                                <span>normalized subjects</span>
                              </div>
                              <button
                                className="analysis-button"
                                type="button"
                                disabled={altState?.status === "loading"}
                                onClick={() => runAltAnalysis(version.id)}
                              >
                                {altState?.status === "loading" ? "Running check..." : "Run ALT check"}
                              </button>
                            </div>
                          </div>

                          {altState?.status === "error" && (
                            <div className="inline-error" role="alert">
                              The ALT result could not be loaded. Confirm that FastAPI and PostgreSQL
                              are running, then try again.
                            </div>
                          )}

                          {altState?.status === "loaded" && (
                            <section className="analysis-result" aria-label="ALT threshold result">
                              <div className="analysis-result-heading">
                                <div>
                                  <p className="card-label">Deterministic result</p>
                                  <h3>ALT greater than 3x upper limit</h3>
                                </div>
                                <span className="method-version">
                                  {altState.response.method_version}
                                </span>
                              </div>

                              <div className="metric-grid">
                                <div>
                                  <strong>{altState.response.eligible_row_count}</strong>
                                  <span>eligible measurements</span>
                                </div>
                                <div>
                                  <strong>{altState.response.qualifying_measurement_count}</strong>
                                  <span>qualifying measurements</span>
                                </div>
                                <div>
                                  <strong>
                                    {altState.response.subjects_with_qualifying_measurement}
                                  </strong>
                                  <span>subjects represented</span>
                                </div>
                              </div>

                              <p className="timing-note">{altState.response.timing_limitation}</p>

                              {altState.response.findings.length > 0 && (
                                <div className="validation-findings">
                                  <strong>
                                    {altState.response.excluded_row_count} measurement
                                    {altState.response.excluded_row_count === 1 ? "" : "s"} excluded
                                  </strong>
                                  <ul>
                                    {altState.response.findings.map((finding) => (
                                      <li
                                        key={`${finding.rule_code}-${finding.source_record_number ?? "all"}`}
                                      >
                                        {finding.message}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              <details className="evidence-panel">
                                <summary>
                                  View source evidence ({altState.response.exceedances.length})
                                </summary>
                                {altState.response.exceedances.length === 0 ? (
                                  <p>No measurements exceeded the threshold.</p>
                                ) : (
                                  <div className="table-scroll">
                                    <table>
                                      <thead>
                                        <tr>
                                          <th>Source row</th>
                                          <th>Subject</th>
                                          <th>ALT result</th>
                                          <th>Upper limit</th>
                                          <th>Threshold</th>
                                          <th>Timing</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {altState.response.exceedances.map((item) => (
                                          <tr key={item.source_record_number}>
                                            <td>{item.source_record_number}</td>
                                            <td>{item.unique_subject_id}</td>
                                            <td>{item.standard_result}</td>
                                            <td>{item.upper_reference_limit}</td>
                                            <td>{item.threshold}</td>
                                            <td>{item.timing.replaceAll("_", " ")}</td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                )}
                              </details>
                            </section>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
