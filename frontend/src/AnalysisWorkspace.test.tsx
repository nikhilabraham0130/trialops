import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalysisWorkspace } from "./AnalysisWorkspace";
import type { AnalysisPlan, AnalysisPlanDetails, GovernanceEvaluation, StoredInterpretation } from "./api/agent";
import type { AltAbnormalityResponse } from "./api/analytics";
import type { StudySummary } from "./api/studies";

const studies: StudySummary[] = [{
  id: "study-1",
  study_oid: "CDISCPILOT01",
  title: null,
  dataset_versions: [{ id: "dataset-1", version_label: "pilot-v1", status: "RECEIVED", subject_count: 306 }],
}];

const proposal: AnalysisPlan = {
  id: "plan-1",
  question: "Were ALT measurements elevated?",
  dataset_version_id: "dataset-1",
  purpose: "Use the approved ALT calculation.",
  status: "AWAITING_CONFIRMATION",
  confirmation_required: true,
  tool_call: {
    name: "calculate_alt_gt_3x_uln",
    arguments: { dataset_version_id: "dataset-1" },
  },
};

const result: AltAbnormalityResponse = {
  dataset_version_id: "dataset-1",
  method_version: "alt-gt-3x-uln/1.0",
  threshold_multiplier: "3",
  alt_row_count: 1814,
  eligible_row_count: 1814,
  excluded_row_count: 0,
  qualifying_measurement_count: 4,
  subjects_with_qualifying_measurement: 3,
  exceedances: [{
    source_record_number: 20065,
    unique_subject_id: "SUBJECT-001",
    standard_result: "104",
    upper_reference_limit: "32",
    threshold: "96",
    timing: "NOT_IDENTIFIED_AS_BASELINE",
  }],
  findings: [],
  timing_limitation: "A blank baseline flag does not prove post-treatment timing.",
};

const interpretation: StoredInterpretation = {
  summary: "The calculation found 4 qualifying measurements across 3 subjects.",
  numeric_claims: [
    { field: "qualifying_measurement_count", value: "4" },
    { field: "subjects_with_qualifying_measurement", value: "3" },
  ],
  grounding_status: "NUMERICALLY_VERIFIED",
  prompt_version: "alt-result-interpretation/1.0",
  model_id: "fake-model",
  generated_at: "2026-09-30T17:00:00Z",
};

afterEach(() => window.history.replaceState(null, "", "/"));

describe("AnalysisWorkspace", () => {
  it("requires a separate confirmation before running the trusted calculation", async () => {
    const user = userEvent.setup();
    const createPlan = vi.fn().mockResolvedValue(proposal);
    const confirmPlan = vi.fn().mockResolvedValue({
      plan_id: "plan-1", status: "EXECUTED", tool_name: "calculate_alt_gt_3x_uln", result,
    });
    const interpretPlan = vi.fn().mockResolvedValue(interpretation);
    render(<AnalysisWorkspace studies={studies} createPlan={createPlan} confirmPlan={confirmPlan}
      interpretPlan={interpretPlan} />);

    await user.type(screen.getByLabelText("Your question"), proposal.question);
    await user.click(screen.getByRole("button", { name: "Propose analysis" }));

    expect(createPlan).toHaveBeenCalledWith(proposal.question, "dataset-1");
    expect(await screen.findByRole("heading", { name: "ALT threshold calculation" })).toBeInTheDocument();
    expect(confirmPlan).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "ALT above 3 × upper limit of normal" })).not.toBeInTheDocument();
    expect(window.location.search).toBe("?plan=plan-1");

    await user.click(screen.getByRole("button", { name: "Confirm and calculate" }));
    expect(confirmPlan).toHaveBeenCalledWith("plan-1");
    expect(await screen.findByRole("heading", { name: "ALT above 3 × upper limit of normal" })).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText(/A blank baseline flag does not prove post-treatment timing/)).toBeInTheDocument();
    expect(screen.getByText("SUBJECT-001")).toBeInTheDocument();
    expect(interpretPlan).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Generate explanation" }));
    expect(interpretPlan).toHaveBeenCalledWith("plan-1");
    expect(await screen.findByText(interpretation.summary)).toBeInTheDocument();
    expect(screen.getByText(/has not received independent clinical review/)).toBeInTheDocument();
  });

  it("restores a completed plan from the URL after refresh", async () => {
    window.history.replaceState(null, "", "/?plan=plan-1");
    const saved: AnalysisPlanDetails = {
      ...proposal,
      status: "EXECUTED",
      confirmation_required: false,
      result,
      interpretation,
      created_at: "2026-09-30T16:00:00Z",
      executed_at: "2026-09-30T16:01:00Z",
    };
    const loadPlan = vi.fn().mockResolvedValue(saved);
    render(<AnalysisWorkspace studies={studies} loadPlan={loadPlan} />);

    expect(await screen.findByText(interpretation.summary)).toBeInTheDocument();
    expect(loadPlan).toHaveBeenCalledWith("plan-1", expect.any(AbortSignal));
    expect(screen.getByRole("heading", { name: "ALT above 3 × upper limit of normal" })).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue(proposal.question);
  });

  it("shows backend governance checks and refreshes them after interpretation", async () => {
    window.history.replaceState(null, "", "/?plan=plan-1");
    const saved: AnalysisPlanDetails = {
      ...proposal,
      status: "EXECUTED",
      confirmation_required: false,
      result,
      interpretation: null,
      created_at: "2026-09-30T16:00:00Z",
      executed_at: "2026-09-30T16:01:00Z",
    };
    const before: GovernanceEvaluation = {
      decision: "NOT_READY_FOR_REVIEW",
      findings: [
        { policy_code: "DETERMINISTIC_RESULT_REQUIRED", status: "PASS", blocking: false,
          message: "The analysis has a stored deterministic result." },
        { policy_code: "NUMERIC_GROUNDING_REQUIRED", status: "FAIL", blocking: true,
          message: "A numerically verified AI interpretation is required before review." },
      ],
    };
    const after: GovernanceEvaluation = {
      decision: "REVIEW_REQUIRED",
      findings: [
        { policy_code: "NUMERIC_GROUNDING_REQUIRED", status: "PASS", blocking: false,
          message: "The AI interpretation passed numeric grounding verification." },
        { policy_code: "INDEPENDENT_REVIEW_REQUIRED", status: "FAIL", blocking: true,
          message: "Independent reviewer approval is required." },
      ],
    };
    const loadGovernance = vi.fn().mockResolvedValueOnce(before).mockResolvedValueOnce(after);
    const user = userEvent.setup();
    render(<AnalysisWorkspace studies={studies} loadPlan={vi.fn().mockResolvedValue(saved)}
      interpretPlan={vi.fn().mockResolvedValue(interpretation)} loadGovernance={loadGovernance} />);

    await user.click(await screen.findByRole("button", { name: "Check current status" }));
    expect(await screen.findByText("Not ready for independent review.")).toBeInTheDocument();
    expect(screen.getByText(before.findings[1].message)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Generate explanation" }));
    expect(await screen.findByText(interpretation.summary)).toBeInTheDocument();
    expect(screen.queryByText("Not ready for independent review.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Check current status" }));
    expect(await screen.findByText("Ready for independent review, but not approved.")).toBeInTheDocument();
    expect(screen.getByText(after.findings[1].message)).toBeInTheDocument();
    expect(loadGovernance).toHaveBeenCalledTimes(2);
  });

  it("reports governance lookup errors without hiding the stored result", async () => {
    window.history.replaceState(null, "", "/?plan=plan-1");
    const saved: AnalysisPlanDetails = {
      ...proposal,
      status: "EXECUTED",
      confirmation_required: false,
      result,
      interpretation: null,
      created_at: "2026-09-30T16:00:00Z",
      executed_at: "2026-09-30T16:01:00Z",
    };
    const user = userEvent.setup();
    render(<AnalysisWorkspace studies={studies} loadPlan={vi.fn().mockResolvedValue(saved)}
      loadGovernance={vi.fn().mockRejectedValue(new Error("The saved plan could not be read."))} />);

    await user.click(await screen.findByRole("button", { name: "Check current status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The saved plan could not be read.");
    expect(screen.getByRole("heading", { name: /ALT above 3/ })).toBeInTheDocument();
  });

  it("keeps the calculation visible when interpretation generation fails", async () => {
    window.history.replaceState(null, "", "/?plan=plan-1");
    const saved: AnalysisPlanDetails = {
      ...proposal,
      status: "EXECUTED",
      confirmation_required: false,
      result,
      interpretation: null,
      created_at: "2026-09-30T16:00:00Z",
      executed_at: "2026-09-30T16:01:00Z",
    };
    const user = userEvent.setup();
    render(<AnalysisWorkspace studies={studies} loadPlan={vi.fn().mockResolvedValue(saved)}
      interpretPlan={vi.fn().mockRejectedValue(new Error("The interpretation model is temporarily unavailable."))} />);

    await user.click(await screen.findByRole("button", { name: "Generate explanation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The interpretation model is temporarily unavailable.");
    expect(screen.getByRole("heading", { name: "ALT above 3 × upper limit of normal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate explanation" })).toBeEnabled();
  });

  it("shows excluded-row findings and explains when no measurement qualifies", async () => {
    window.history.replaceState(null, "", "/?plan=plan-1");
    const saved: AnalysisPlanDetails = {
      ...proposal,
      status: "EXECUTED",
      confirmation_required: false,
      result: {
        ...result,
        excluded_row_count: 1,
        qualifying_measurement_count: 0,
        subjects_with_qualifying_measurement: 0,
        exceedances: [],
        findings: [{
          rule_code: "ALT_LIMIT_MISSING",
          severity: "WARNING",
          domain: "LB",
          source_record_number: null,
          message: "One ALT row lacked a usable upper limit.",
        }],
      },
      interpretation: null,
      created_at: "2026-09-30T16:00:00Z",
      executed_at: "2026-09-30T16:01:00Z",
    };
    render(<AnalysisWorkspace studies={studies} loadPlan={vi.fn().mockResolvedValue(saved)} />);

    expect(await screen.findByText("No measurements exceeded the threshold.")).toBeInTheDocument();
    expect(screen.getByText("One ALT row lacked a usable upper limit.")).toBeInTheDocument();
    expect(screen.getByText("1 excluded measurement(s)")).toBeInTheDocument();
  });

  it("shows a failed plan request without claiming a calculation ran", async () => {
    const user = userEvent.setup();
    const createPlan = vi.fn().mockRejectedValue(new Error("The planning model is temporarily unavailable."));
    render(<AnalysisWorkspace studies={studies} createPlan={createPlan} />);

    await user.type(screen.getByLabelText("Your question"), "Check ALT.");
    await user.click(screen.getByRole("button", { name: "Propose analysis" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The planning model is temporarily unavailable.");
    expect(screen.queryByRole("heading", { name: "ALT threshold calculation" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Propose analysis" })).toBeEnabled();
  });

  it("retains the proposed plan after a calculation error so it can be retried", async () => {
    const user = userEvent.setup();
    render(<AnalysisWorkspace studies={studies} createPlan={vi.fn().mockResolvedValue(proposal)}
      confirmPlan={vi.fn().mockRejectedValue(new Error("The analysis could not be executed safely."))} />);

    await user.type(screen.getByLabelText("Your question"), proposal.question);
    await user.click(screen.getByRole("button", { name: "Propose analysis" }));
    await user.click(await screen.findByRole("button", { name: "Confirm and calculate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The analysis could not be executed safely.");
    expect(screen.getByRole("heading", { name: "ALT threshold calculation" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "ALT above 3 × upper limit of normal" })).not.toBeInTheDocument();
  });

  it("reports when a saved analysis link cannot be loaded", async () => {
    window.history.replaceState(null, "", "/?plan=missing-plan");
    render(<AnalysisWorkspace studies={studies} loadPlan={vi.fn().mockRejectedValue(new Error("The requested analysis plan does not exist."))} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The requested analysis plan does not exist.");
    expect(screen.getByRole("button", { name: "Propose analysis" })).toBeDisabled();
  });

  it("ignores an older saved-plan response after its request is cancelled", async () => {
    window.history.replaceState(null, "", "/?plan=plan-1");
    let finishOldRequest!: (value: AnalysisPlanDetails) => void;
    const oldRequest = vi.fn(() => new Promise<AnalysisPlanDetails>((resolve) => {
      finishOldRequest = resolve;
    }));
    const currentPlan: AnalysisPlanDetails = {
      ...proposal,
      question: "Current saved question",
      result: null,
      interpretation: null,
      created_at: "2026-09-30T16:00:00Z",
      executed_at: null,
    };
    const latestRequest = vi.fn().mockResolvedValue(currentPlan);
    const { rerender } = render(<AnalysisWorkspace studies={studies} loadPlan={oldRequest} />);

    rerender(<AnalysisWorkspace studies={studies} loadPlan={latestRequest} />);
    expect(await screen.findByRole("button", { name: "Confirm and calculate" })).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("Current saved question");

    await act(async () => finishOldRequest({ ...currentPlan, question: "Stale saved question" }));
    expect(screen.queryByText("Stale saved question")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("Current saved question");
  });

  it("lets the user select a different dataset version for a new plan", async () => {
    const user = userEvent.setup();
    const createPlan = vi.fn().mockResolvedValue({ ...proposal, dataset_version_id: "dataset-2" });
    const twoVersions: StudySummary[] = [{
      ...studies[0],
      dataset_versions: [
        ...studies[0].dataset_versions,
        { id: "dataset-2", version_label: "pilot-v2", status: "VALID", subject_count: 310 },
      ],
    }];
    render(<AnalysisWorkspace studies={twoVersions} createPlan={createPlan} />);

    await user.selectOptions(screen.getByLabelText("Dataset version"), "dataset-2");
    await user.type(screen.getByLabelText("Your question"), "Check ALT.");
    await user.click(screen.getByRole("button", { name: "Propose analysis" }));

    expect(createPlan).toHaveBeenCalledWith("Check ALT.", "dataset-2");
  });
});
