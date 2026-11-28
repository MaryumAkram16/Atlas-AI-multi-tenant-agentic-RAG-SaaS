import { LOGO_ACCENT_PATH, LOGO_ASPECT, LOGO_PRIMARY_PATH, LOGO_VIEWBOX } from "./logoPaths";

export interface LogoProps {
  /** "full": symbol + "Atlas AI" wordmark; "symbol": the mark alone. */
  variant?: "full" | "symbol";
  /** Height of the symbol in pixels; the wordmark scales with it. */
  size?: number;
  /** "auto" follows the site theme; "light"/"dark" force the colours for that background. */
  theme?: "auto" | "light" | "dark";
  className?: string;
}

/** The Atlas AI logo. Colours come from CSS (--logo-primary, --logo-accent), so it
 * adapts to light and dark themes without separate files. */
export function Logo({ variant = "full", size = 28, theme = "auto", className = "" }: LogoProps) {
  const symbolOnly = variant === "symbol";
  const classes = ["logo", theme !== "auto" ? `logo--${theme}` : "", className].filter(Boolean).join(" ");
  return (
    <span className={classes} role={symbolOnly ? "img" : undefined} aria-label={symbolOnly ? "Atlas AI" : undefined}>
      <svg
        className="logo-symbol"
        viewBox={LOGO_VIEWBOX}
        width={Math.round(size * LOGO_ASPECT)}
        height={size}
        aria-hidden="true"
        focusable="false"
      >
        <path className="logo-primary" d={LOGO_PRIMARY_PATH} />
        <path className="logo-accent" d={LOGO_ACCENT_PATH} />
      </svg>
      {!symbolOnly && (
        <span className="logo-word" style={{ fontSize: `${(size * 0.69).toFixed(1)}px` }}>
          Atlas AI
        </span>
      )}
    </span>
  );
}

/** Full-screen loading state with the symbol above a spinner. */
export function LoadingScreen({ label = "Loading" }: { label?: string }) {
  return (
    <div className="center loading-screen" role="status" aria-label={label}>
      <Logo variant="symbol" size={44} />
      <span className="spinner" aria-hidden="true">
        <span className="spinner-dot" />
      </span>
    </div>
  );
}
