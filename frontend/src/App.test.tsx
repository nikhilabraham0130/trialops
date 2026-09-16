import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
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
});
