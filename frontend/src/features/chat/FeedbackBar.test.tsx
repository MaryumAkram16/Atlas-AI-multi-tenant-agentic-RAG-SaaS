import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FeedbackBar } from "./FeedbackBar";

describe("FeedbackBar", () => {
  it("sends a thumbs up directly", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<FeedbackBar value={null} onSave={onSave} onClear={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ rating: "up" }));
  });

  it("asks for a reason on thumbs down and says who sees it", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<FeedbackBar value={null} onSave={onSave} onClear={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));
    expect(screen.getByText(/shared with workspace admins/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Wrong citation"));
    fireEvent.change(screen.getByLabelText("Feedback comment"), { target: { value: " cites 2024 " } });
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({ rating: "down", reason: "wrong_citation", comment: "cites 2024" }),
    );
  });

  it("clicking the active rating removes it", async () => {
    const onClear = vi.fn().mockResolvedValue(undefined);
    const value = { message_id: "m", rating: "up" as const, reason: null, comment: null, created_at: "", updated_at: "" };
    render(<FeedbackBar value={value} onSave={vi.fn()} onClear={onClear} />);
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    await waitFor(() => expect(onClear).toHaveBeenCalled());
  });
});
