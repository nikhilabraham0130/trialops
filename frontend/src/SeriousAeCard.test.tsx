import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SeriousAeIncidenceResponse } from "./api/analytics";
import { SeriousAeCard } from "./SeriousAeCard";

const result: SeriousAeIncidenceResponse = {
  dataset_version_id: "version-1",
  method_version: "serious-ae-incidence/1.0",
  excluded_screen_failure_subjects: 2,
  population_definition: "DM subjects grouped by ACTARM.",
  timing_limitation: "AESER = Y; not confirmed treatment-emergent.",
  arms: [{
    arm: "Placebo",
    subjects_in_arm: 3,
    subjects_with_serious_ae: 1,
    serious_ae_event_count: 2,
    incidence_percent: "33.33",
  }],
  evidence: [{
    source_record_number: 42,
    unique_subject_id: "SUBJECT-001",
    arm: "Placebo",
    preferred_term: "Headache",
  }],
};

describe("SeriousAeCard", () => {
  it("shows the backend's serious-AE counts and source rows", async () => {
    const loadAnalysis = vi.fn().mockResolvedValue(result);
    render(<SeriousAeCard datasetVersionId="version-1" loadAnalysis={loadAnalysis} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Run serious-AE check" }));

    expect(loadAnalysis).toHaveBeenCalledWith("version-1");
    expect(await screen.findByRole("region", { name: "Serious AE incidence result" })).toBeInTheDocument();
    expect(screen.getByText("33.33%")).toBeInTheDocument();
    expect(screen.getByText(/2 screen-failure subject/)).toBeInTheDocument();
    expect(screen.getByText("SUBJECT-001")).toBeInTheDocument();
    expect(screen.getByText("AESER = Y; not confirmed treatment-emergent.")).toBeInTheDocument();
  });
});
