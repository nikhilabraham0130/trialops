import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuditPanel } from "./AuditPanel";

describe("AuditPanel", () => {
  it("loads only the selected entity when requested", async () => {
    const load = vi.fn().mockResolvedValue([{
      id: "event-1", created_at: "2026-10-01T00:00:00Z", actor_id: "local-operator",
      action: "ANALYSIS_CREATED", entity_type: "agent_plan", entity_id: "plan-1", details: {},
    }]);
    const user = userEvent.setup();
    render(<AuditPanel entityId="plan-1" load={load} />);
    expect(load).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Load audit history" }));
    expect(load).toHaveBeenCalledWith("plan-1");
    expect(await screen.findByText("ANALYSIS CREATED")).toBeInTheDocument();
  });
});
