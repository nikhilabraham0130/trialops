import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SubjectSafetySummaryResponse } from "./api/analytics";
import { SubjectSafetyCard } from "./SubjectSafetyCard";

const result: SubjectSafetySummaryResponse = {
  dataset_version_id: "version-1",
  method_version: "subject-safety-summary/1.0",
  unique_subject_id: "SUBJECT-001",
  actual_arm: "Placebo",
  age: 55,
  age_unit: "YEARS",
  sex: "F",
  ae_event_count: 1,
  severe_ae_event_count: 1,
  serious_ae_event_count: 0,
  lab_result_count: 2,
  flagged_lab_count: 1,
  events: [{
    source_record_number: 10,
    preferred_term: "Headache",
    severity: "SEVERE",
    serious_flag: "N",
    start_date_text: "2020-01-01",
  }],
  flagged_labs: [{
    source_record_number: 20,
    test_code: "ALT",
    standard_result: "55",
    standard_unit: "U/L",
    lower_reference_limit: "10",
    upper_reference_limit: "40",
    range_indicator: "HIGH",
    baseline_flag: null,
    observed_at_text: "2020-01-02",
  }],
  interpretation_limit: "These are descriptive source classifications.",
};

describe("SubjectSafetyCard", () => {
  it("loads one subject and displays separate AE and lab source evidence", async () => {
    const loadSummary = vi.fn().mockResolvedValue(result);
    const user = userEvent.setup();
    render(<SubjectSafetyCard datasetVersionId="version-1" loadSummary={loadSummary} />);

    await user.type(screen.getByRole("textbox", { name: /Unique subject ID/ }), " SUBJECT-001 ");
    await user.click(screen.getByRole("button", { name: "View subject" }));

    expect(loadSummary).toHaveBeenCalledWith("version-1", "SUBJECT-001");
    expect(await screen.findByText("These are descriptive source classifications.")).toBeInTheDocument();
    expect(screen.getByText("Headache")).toBeInTheDocument();
    expect(screen.getByText("ALT")).toBeInTheDocument();
  });

  it("keeps lookup available after an API failure", async () => {
    const user = userEvent.setup();
    render(<SubjectSafetyCard datasetVersionId="version-1"
      loadSummary={vi.fn().mockRejectedValue(new Error("Not found"))} />);
    await user.type(screen.getByRole("textbox", { name: /Unique subject ID/ }), "missing");
    await user.click(screen.getByRole("button", { name: "View subject" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.getByRole("button", { name: "View subject" })).toBeEnabled();
  });
});
