import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SQLWorkbench } from "./SQLWorkbench";

describe("SQLWorkbench", () => {
  it("displays the backend-normalized query and rows", async () => {
    const execute = vi.fn().mockResolvedValue({
      dataset_version_id: "version-1",
      validated_sql: "SELECT actual_arm, COUNT(*) AS subjects FROM vw_subjects GROUP BY actual_arm LIMIT 100",
      row_count: 1, row_limit: 100,
      rows: [{ actual_arm: "Placebo", subjects: 86 }],
    });
    const user = userEvent.setup();
    render(<SQLWorkbench datasetVersionId="version-1" execute={execute} />);

    await user.click(screen.getByRole("button", { name: "Run read-only query" }));

    expect(execute).toHaveBeenCalledWith(
      "version-1", "SELECT actual_arm, COUNT(*) AS subjects FROM vw_subjects GROUP BY actual_arm",
    );
    expect(await screen.findByLabelText("Governed SQL result")).toHaveTextContent("Placebo");
    expect(screen.getByText("86")).toBeInTheDocument();
    expect(screen.getByText(/LIMIT 100/)).toBeInTheDocument();
  });

  it("keeps the query editable after a rejected request", async () => {
    const user = userEvent.setup();
    render(<SQLWorkbench datasetVersionId="version-1"
      execute={vi.fn().mockRejectedValue(new Error("Only one SELECT is permitted."))} />);
    await user.click(screen.getByRole("button", { name: "Run read-only query" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only one SELECT is permitted.");
    expect(screen.getByRole("textbox", { name: "SQL query" })).toBeEnabled();
  });
});
