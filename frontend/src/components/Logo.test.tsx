import { render, screen } from "@testing-library/react";
import { LoadingScreen, Logo } from "./Logo";

describe("Logo", () => {
  it("renders the symbol and the wordmark by default", () => {
    const { container } = render(<Logo />);
    expect(screen.getByText("Atlas AI")).toBeInTheDocument();
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true"); // the visible text names it
    expect(svg.querySelectorAll("path")).toHaveLength(2);
    expect(container.querySelector("image, img")).toBeNull(); // vector only
  });

  it("symbol-only variant is a labelled image at the requested size", () => {
    const { container } = render(<Logo variant="symbol" size={16} />);
    expect(screen.getByRole("img", { name: "Atlas AI" })).toBeInTheDocument();
    expect(screen.queryByText("Atlas AI")).toBeNull();
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("height", "16");
    expect(Number(svg.getAttribute("width"))).toBeGreaterThan(16); // the mark is wider than tall
  });

  it("can force light or dark colours", () => {
    const { container } = render(<Logo theme="light" />);
    expect(container.firstChild).toHaveClass("logo", "logo--light");
  });

  it("loading screen shows the symbol with a status role", () => {
    render(<LoadingScreen label="Opening" />);
    expect(screen.getByRole("status", { name: "Opening" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Atlas AI" })).toBeInTheDocument();
  });
});
