# Architectural Decisions Log

This document records the key technical, design, and architectural decisions made in the MyBullAndBear project, including rationale, trade-offs, and alternatives considered.

---

### DEC-001: Neumorphic Dark Theme as Master Design System
- **Status**: ACCEPTED
- **Date**: 2026-11-01
- **Context**: The terminal previously had disparate styles across different tabs (`terminal.css`, `decision-board.css`, `modern-terminal.css`, `tokens.css`), leading to inconsistent elevation, borders, and tactile feel.
- **Decision**: Unify the entire application under a dedicated **Neumorphic Dark Theme** (`neumorphism.css`):
  - Extruded surfaces (`.nm-card`, `.nm-raised`) for cards, header, and floating panels using organic top-left illumination and bottom-right depth shadows.
  - Recessed wells (`.nm-well`, `.nm-inset`) for live charts, data tables, and telemetry feeds.
  - Tactile interactive controls (`.nm-btn`, `.nm-tab`, `.nm-pill`) that depress into smooth inset states on click.
  - High-contrast typography (`Inter`, `JetBrains Mono`) ensuring zero readability sacrifice.
- **Consequences**: Consistent, premium look and feel across all 5 core modules (Decision Board, Confluence, Option Chain, Bot, OI Analytics).

---

### DEC-002: ATM +- 3 Strikes Intraday Sparklines Infusion
- **Status**: ACCEPTED
- **Date**: 2026-11-01
- **Context**: Traders reviewing the Sensibull Option Chain Matrix needed immediate visibility into how Open Interest ($\Delta\text{OI}$) and Option Premium (LTP) evolved over the trading session for the strikes closest to money.
- **Decision**: Enrich the option chain payload with downsampled 25–30 point timeseries for the 7 strikes centered at ATM ($\text{ATM}-3$ to $\text{ATM}+3$, 14 contracts: CE & PE). Render inline SVG `<polyline>` sparklines with green/red for price trajectory and sky-blue/amber for OI accumulation.
- **Trade-offs**: Restricting sparklines strictly to ATM $\pm$ 3 strikes prevents DOM bloat, keeping table scrolling silky smooth while highlighting the exact action zone.

---

### DEC-003: Dynamic Host Resolution for Broker Authentication Callbacks
- **Status**: ACCEPTED
- **Date**: 2026-11-01
- **Context**: Broker OAuth redirects previously broke whenever the deployment IP changed or when accessing the terminal through reverse proxies or custom ports.
- **Decision**: Infer the callback redirect URI dynamically from the incoming HTTP `request.headers.get("host")`. Support both direct token exchange and manual authorization code pasting.
- **Consequences**: Zero redirect failures regardless of whether accessed via local IP, remote VM IP (`137.23.63.209`), or domain.

---

### DEC-004: Strict Scroll Position Preservation on Live Polling Ticks
- **Status**: ACCEPTED
- **Date**: 2026-11-01
- **Context**: Rapid 2-to-4-second background market polling ticks caused the Option Chain Matrix and OI tables to reset their scroll position to the top, disrupting user analysis.
- **Decision**: Save `scrollLeft` and `scrollTop` prior to DOM updates, and re-apply them after DOM synchronization. Pause DOM re-renders while the user is actively touching or scrolling on mobile (`isUserTouchingChain = true`).
- **Consequences**: Completely stable scrolling without jitter or gesture cancellation.

---

### DEC-005: Project Memory Agent for Future Continuity
- **Status**: ACCEPTED
- **Date**: 2026-11-01
- **Context**: AI pair programming across multiple sessions risked losing context, re-introducing past regressions, or altering critical files (such as credentials).
- **Decision**: Formally integrate the Project Memory Agent into the workspace root (`AGENTS.md`, `docs/PROJECT_STATE.md`, `docs/CHANGELOG.md`, `docs/DECISIONS.md`).
- **Consequences**: Every future agent must verify recorded facts before making claims, preserve credentials, and update documentation before concluding.
