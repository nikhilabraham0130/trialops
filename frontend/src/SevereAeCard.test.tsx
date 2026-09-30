import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SevereAeCard } from "./SevereAeCard";
import type { SevereAeIncidenceResponse } from "./api/analytics";

const result: SevereAeIncidenceResponse = {
  dataset_version_id: "version-1",
  method_version: "severe-ae-incidence/1.0",
  excluded_screen_failure_subjects: 2,
  population_definition: "All DM subjects grouped by ACTARM.",
  timing_limitation: "These are not confirmed treatment-emergent events.",
  arms: [{
    arm: "Placebo",
    subjects_in_arm: 3,
    subjects_with_severe_ae: 1,
    severe_ae_event_count: 2,
    incidence_percent: "33.33",
  }],
  evidence: [{
    source_record_number: 42,
    unique_subject_id: "SUBJECT-001",
    arm: "Placebo",
    preferred_term: "Headache",
  }],
};

describe("SevereAeCard", () => {
  it("shows backend counts and timing limits without recalculating incidence", async () => {
    const loadAnalysis = vi.fn().mockResolvedValue(result);
    const user = userEvent.setup();
    render(<SevereAeCard datasetVersionId="version-1" loadAnalysis={loadAnalysis} />);

    await user.click(screen.getByRole("button", { name: "Run severe-AE check" }));

    expect(loadAnalysis).toHaveBeenCalledWith("version-1");
    expect(await screen.findByRole("region", { name: "Severe AE incidence result" })).toBeInTheDocument();
    expect(screen.getByText("33.33%")).toBeInTheDocument();
    expect(screen.getByText(/2 screen-failure subject/)).toBeInTheDocument();
    expect(screen.getByText("These are not confirmed treatment-emergent events.")).toBeInTheDocument();
    expect(screen.getByText("SUBJECT-001")).toBeInTheDocument();
  });

  it("keeps a retry available after an API error", async () => {
    const loadAnalysis = vi.fn().mockRejectedValue(new Error("Database unavailable"));
    const user = userEvent.setup();
    render(<SevereAeCard datasetVersionId="version-1" loadAnalysis={loadAnalysis} />);

    await user.click(screen.getByRole("button", { name: "Run severe-AE check" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.getByRole("button", { name: "Run severe-AE check" })).toBeEnabled();
  });

  it("explains when no severe AE rows exist", async () => {
    const user = userEvent.setup();
    render(<SevereAeCard datasetVersionId="version-1"
      loadAnalysis={vi.fn().mockResolvedValue({ ...result, evidence: [] })} />);

    await user.click(screen.getByRole("button", { name: "Run severe-AE check" }));

    expect(await screen.findByText("No recorded severe adverse events were found.")).toBeInTheDocument();
  });
});
