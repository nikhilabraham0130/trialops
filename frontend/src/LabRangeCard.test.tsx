import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LabRangeResponse } from "./api/analytics";
import { LabRangeCard } from "./LabRangeCard";

const result: LabRangeResponse = {
  dataset_version_id: "version-1",
  method_version: "lab-reference-range/1.0",
  test_code: "AST",
  total_rows: 3,
  eligible_rows: 2,
  excluded_rows: 1,
  below_lower_rows: 0,
  above_upper_rows: 1,
  out_of_range_rows: 1,
  subjects_with_out_of_range: 1,
  evidence: [{
    source_record_number: 42,
    unique_subject_id: "SUBJECT-001",
    standard_result: "41",
    standard_unit: "U/L",
    lower_reference_limit: "0",
    upper_reference_limit: "40",
    direction: "ABOVE_UPPER",
    baseline_flag: null,
  }],
  evidence_truncated: false,
  interpretation_limit: "No treatment timing inferred.",
};

describe("LabRangeCard", () => {
  it("sends an exact test code and displays backend counts and exclusions", async () => {
    const loadAnalysis = vi.fn().mockResolvedValue(result);
    render(<LabRangeCard datasetVersionId="version-1" loadAnalysis={loadAnalysis} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Check lab reference range" }));

    expect(loadAnalysis).toHaveBeenCalledWith("version-1", "AST");
    expect(await screen.findByRole("region", { name: "Lab reference range result" })).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 eligible measurements/)).toBeInTheDocument();
    expect(screen.getByText(/1 of 3 rows excluded/)).toBeInTheDocument();
    expect(screen.getByText("SUBJECT-001")).toBeInTheDocument();
  });
});
