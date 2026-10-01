import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReviewPanel } from "./ReviewPanel";
import type { ReviewStatus } from "./api/reviews";

const draft: ReviewStatus = {
  plan_id: "plan-1", state: "DRAFT", submitted_by: null, submitted_at: null, history: [],
};

describe("ReviewPanel", () => {
  it("submits only after a grounded result and analyst token are available", async () => {
    const submit = vi.fn().mockResolvedValue({
      ...draft, state: "PENDING_REVIEW", submitted_by: "local-analyst",
      submitted_at: "2026-10-01T00:00:00Z", history: [],
    });
    const user = userEvent.setup();
    render(<ReviewPanel planId="plan-1" readyToSubmit
      load={vi.fn().mockResolvedValue(draft)} submit={submit} />);
    await user.click(screen.getByRole("button", { name: "Load review status" }));
    const button = await screen.findByRole("button", { name: "Submit for review" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("Local role token"), "analyst-secret");
    await user.click(button);
    expect(submit).toHaveBeenCalledWith("plan-1", "analyst-secret");
    expect(await screen.findByText("PENDING REVIEW")).toBeInTheDocument();
    expect(screen.getByLabelText("Local role token")).toHaveValue("");
  });

  it("requires a comment before rejecting a pending analysis", async () => {
    const decide = vi.fn().mockResolvedValue({ ...draft, state: "REJECTED" });
    const user = userEvent.setup();
    render(<ReviewPanel planId="plan-1" readyToSubmit
      load={vi.fn().mockResolvedValue({ ...draft, state: "PENDING_REVIEW" })}
      decide={decide} />);
    await user.click(screen.getByRole("button", { name: "Load review status" }));
    const reject = await screen.findByRole("button", { name: "Reject" });
    await user.type(screen.getByLabelText("Local role token"), "reviewer-secret");
    expect(reject).toBeDisabled();
    await user.type(screen.getByLabelText("Reviewer comment"), "Evidence needs review.");
    await user.click(reject);
    expect(decide).toHaveBeenCalledWith("plan-1", "reviewer-secret", "REJECTED", "Evidence needs review.");
  });
});
