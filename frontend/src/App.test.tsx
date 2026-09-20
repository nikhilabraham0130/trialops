import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AltAbnormalityResponse } from "./api/analytics";
import type { StudyListResponse } from "./api/studies";

const populatedResponse: StudyListResponse = {
  studies: [
    {
      id: "study-1",
      study_oid: "CDISCPILOT01",
      title: null,
      dataset_versions: [
        {
          id: "dataset-1",
          version_label: "cdisc-pilot-667511d4",
          status: "RECEIVED",
          subject_count: 306,
        },
      ],
    },
  ],
};

const altResponse: AltAbnormalityResponse = {
  dataset_version_id: "dataset-1",
  method_version: "alt-gt-3x-uln/1.0",
  threshold_multiplier: "3",
  alt_row_count: 2,
  eligible_row_count: 1,
  excluded_row_count: 1,
  qualifying_measurement_count: 1,
  subjects_with_qualifying_measurement: 1,
  exceedances: [
    {
      source_record_number: 10,
      unique_subject_id: "SUBJECT-001",
      standard_result: "150.5",
      upper_reference_limit: "40",
      threshold: "120",
      timing: "NOT_IDENTIFIED_AS_BASELINE",
    },
  ],
  findings: [
    {
      rule_code: "ALT_RESULT_MISSING_OR_INVALID",
      severity: "WARNING",
      domain: "LB",
      source_record_number: 11,
      message: "ALT result is missing or not a finite number.",
    },
  ],
  timing_limitation: "A blank baseline flag does not prove post-treatment timing.",
};

describe("App", () => {
  it("shows a loading state while the API request is pending", () => {
    const requestThatNeverCompletes = vi.fn(() => new Promise<StudyListResponse>(() => undefined));

    render(<App loadStudies={requestThatNeverCompletes} />);

    expect(screen.getByText("Loading registered studies…")).toBeInTheDocument();
  });

  it("shows studies and their normalized subject counts", async () => {
    render(<App loadStudies={vi.fn().mockResolvedValue(populatedResponse)} />);

    expect(await screen.findByRole("heading", { name: "CDISCPILOT01" })).toBeInTheDocument();
    expect(screen.getByText("cdisc-pilot-667511d4")).toBeInTheDocument();
    expect(screen.getByText("306")).toBeInTheDocument();
    expect(screen.getByText("normalized subjects")).toBeInTheDocument();
  });

  it("shows a study title, identifier, and plural dataset-version count", async () => {
    const titledResponse: StudyListResponse = {
      studies: [
        {
          ...populatedResponse.studies[0],
          title: "Alzheimer's Disease Pilot Study",
          dataset_versions: [
            ...populatedResponse.studies[0].dataset_versions,
            {
              id: "dataset-2",
              version_label: "cdisc-pilot-follow-up",
              status: "VALID",
              subject_count: 310,
            },
          ],
        },
      ],
    };

    render(<App loadStudies={vi.fn().mockResolvedValue(titledResponse)} />);

    expect(
      await screen.findByRole("heading", { name: "Alzheimer's Disease Pilot Study" }),
    ).toBeInTheDocument();
    expect(screen.getByText("CDISCPILOT01")).toBeInTheDocument();
    expect(screen.getByText("2 dataset versions")).toBeInTheDocument();
  });

  it("explains when no studies have been registered", async () => {
    render(<App loadStudies={vi.fn().mockResolvedValue({ studies: [] })} />);

    expect(await screen.findByText("No studies are registered yet.")).toBeInTheDocument();
  });

  it("shows a useful error when the API request fails", async () => {
    render(<App loadStudies={vi.fn().mockRejectedValue(new Error("network unavailable"))} />);

    expect(
      await screen.findByRole("alert", { name: "" }),
    ).toHaveTextContent("The study catalog could not be loaded.");
  });

  it("does not turn a deliberately aborted request into an error", async () => {
    const abortedRequest = vi
      .fn()
      .mockRejectedValue(new DOMException("The request was cancelled.", "AbortError"));

    render(<App loadStudies={abortedRequest} />);

    await waitFor(() => expect(abortedRequest).toHaveBeenCalledOnce());
    await act(async () => undefined);
    expect(screen.getByText("Loading registered studies…")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("requests and displays deterministic ALT counts and evidence", async () => {
    const loadAltAnalysis = vi.fn().mockResolvedValue(altResponse);
    const user = userEvent.setup();
    render(
      <App
        loadStudies={vi.fn().mockResolvedValue(populatedResponse)}
        loadAltAnalysis={loadAltAnalysis}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Run ALT check" }));

    expect(loadAltAnalysis).toHaveBeenCalledWith("dataset-1");
    expect(await screen.findByRole("heading", { name: "ALT greater than 3x upper limit" }))
      .toBeInTheDocument();
    expect(screen.getByText("alt-gt-3x-uln/1.0")).toBeInTheDocument();
    expect(screen.getByText("eligible measurements").previousElementSibling).toHaveTextContent("1");
    expect(screen.getByText("qualifying measurements").previousElementSibling).toHaveTextContent(
      "1",
    );
    expect(screen.getByText("subjects represented").previousElementSibling).toHaveTextContent("1");
    expect(screen.getByText("1 measurement excluded")).toBeInTheDocument();
    expect(screen.getByText("ALT result is missing or not a finite number.")).toBeInTheDocument();
    expect(screen.getByText("SUBJECT-001")).toBeInTheDocument();
    expect(screen.getByText("NOT IDENTIFIED AS BASELINE")).toBeInTheDocument();
  });

  it("disables the ALT button while the request is running", async () => {
    const pending = vi.fn(() => new Promise<AltAbnormalityResponse>(() => undefined));
    const user = userEvent.setup();
    render(<App loadStudies={vi.fn().mockResolvedValue(populatedResponse)} loadAltAnalysis={pending} />);

    const button = await screen.findByRole("button", { name: "Run ALT check" });
    await user.click(button);

    expect(screen.getByRole("button", { name: "Running check..." })).toBeDisabled();
  });

  it("shows a useful error when the ALT request fails", async () => {
    const user = userEvent.setup();
    render(
      <App
        loadStudies={vi.fn().mockResolvedValue(populatedResponse)}
        loadAltAnalysis={vi.fn().mockRejectedValue(new Error("API unavailable"))}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Run ALT check" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The ALT result could not be loaded.",
    );
  });

  it("explains when no ALT measurements exceeded the threshold", async () => {
    const user = userEvent.setup();
    const noExceedances: AltAbnormalityResponse = {
      ...altResponse,
      excluded_row_count: 0,
      qualifying_measurement_count: 0,
      subjects_with_qualifying_measurement: 0,
      exceedances: [],
      findings: [],
    };
    render(
      <App
        loadStudies={vi.fn().mockResolvedValue(populatedResponse)}
        loadAltAnalysis={vi.fn().mockResolvedValue(noExceedances)}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Run ALT check" }));

    expect(await screen.findByText("No measurements exceeded the threshold.")).toBeInTheDocument();
    expect(screen.queryByText(/measurement excluded/)).not.toBeInTheDocument();
  });
});
