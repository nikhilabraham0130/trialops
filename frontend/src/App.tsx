import { useEffect, useState } from "react";

import { getStudies, type StudyListResponse } from "./api/studies";
import "./styles.css";

type LoadStudies = (signal?: AbortSignal) => Promise<StudyListResponse>;

type StudyState =
  | { status: "loading" }
  | { status: "loaded"; response: StudyListResponse }
  | { status: "error" };

interface AppProps {
  loadStudies?: LoadStudies;
}

export function App({ loadStudies = getStudies }: AppProps) {
  const [state, setState] = useState<StudyState>({ status: "loading" });

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
                    {study.dataset_versions.map((version) => (
                      <div className="version-row" key={version.id}>
                        <div>
                          <p className="version-label">{version.version_label}</p>
                          <span className={`status status-${version.status.toLowerCase()}`}>
                            {version.status.replaceAll("_", " ")}
                          </span>
                        </div>
                        <div className="subject-total">
                          <strong>{version.subject_count.toLocaleString()}</strong>
                          <span>normalized subjects</span>
                        </div>
                      </div>
                    ))}
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
