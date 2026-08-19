# Asymmetry warning uses personal-baseline drift and backstop, not a universal 10% rule

GripTrack tracks bilateral asymmetry across Left and Right hands for trained grip and
edge combinations (issues #46, #47, #48), showing both strength max gaps and training
load volume gaps. Issue #48 adds automated detection for concerning bilateral imbalance
trends. This ADR records why we chose a personal-baseline drift rule with an absolute
backstop rather than a conventional static threshold (such as a universal 10% rule).

## Decision

**Detect asymmetry warning via a dual-arm heuristic: personal-baseline drift (>= 5.0 pp)
with an absolute backstop (>= 15.0%), gated by a minimum data history.**

- **Personal-baseline drift arm (>= 5.0 pp widening):**
  Compare the user's recent load asymmetry window (trailing 3 bilateral sessions) to
  their baseline window (up to 6 bilateral sessions immediately preceding the recent
  window, requiring at least 3 baseline sessions). If `recent - baseline >= 5.0`
  percentage points, flag an `AsymmetryWarning`.
- **Absolute backstop arm (>= 15.0% recent asymmetry):**
  If recent load asymmetry reaches or exceeds 15.0% (`recent >= 15.0%`), flag an
  `AsymmetryWarning` regardless of baseline drift, providing an upper guardrail against
  gradual long-term drift or severe absolute imbalance.
- **Thin data silence (minimum 6 bilateral sessions):**
  Evaluating asymmetry warning requires at least 6 non-deload bilateral sessions
  (`ASYM_RECENT_SESSIONS + ASYM_MIN_BASELINE_SESSIONS = 3 + 3 = 6`). If fewer than 6
  bilateral sessions exist for the combination, the warning remains silent (gates both arms).
- **Widening only:**
  Gaps are evaluated using absolute magnitude `abs(gap)` to measure distance from parity.
  A narrowing gap (improving balance toward parity) yields a negative difference and never warns.
- **Tuning constants:**
  Thresholds and window sizes are module-level constants in `backend/analytics.py`
  (`ASYM_RECENT_SESSIONS = 3`, `ASYM_BASELINE_SESSIONS = 6`, `ASYM_MIN_BASELINE_SESSIONS = 3`,
  `ASYM_DRIFT_PP = 5.0`, `ASYM_BACKSTOP_PCT = 15.0`) rather than magic numbers.

## Why / Literature Context

- **Upper-limb dominance naturally exhibits ~10–12% asymmetry:**
  A common folk rule in strength training proposes flagging any bilateral difference over
  10%. However, sports science and normative hand-grip literature (e.g., Incel et al., 2002;
  Petersen et al., 1989; Crosby et al., 1994) consistently show that healthy populations
  exhibit an average ~10% to ~11.6% strength superiority in the dominant hand. In climbing-specific
  research, there is no consensus universal asymmetry threshold predictive of injury.
- **Static thresholds cause false-alarm fatigue:**
  Applying a universal 10% cutoff would permanently flag healthy climbers whose natural
  limb dominance is 11–12%, teaching them to ignore dashboard warnings.
- **Change detection is the clinically and practically meaningful signal:**
  A climber whose habitual asymmetry is 8% who suddenly widens to 14% (+6 pp drift) is
  experiencing an acute deviation that may indicate unilateral fatigue, compensation, or
  emerging irritation. By comparing recent sessions to the climber's own trailing baseline,
  we detect genuine drift while honoring individual physiology.
- **The 15% backstop catches extreme divergence:**
  While natural dominance rarely exceeds ~12%, severe asymmetry (> 15%) warrants attention
  even if it crept up gradually across many sessions.
- **Silence on thin data preserves trust:**
  Evaluating bilateral stability requires sufficient observations. Premature alerts on 1–2
  variable sessions would produce noisy false positives during onboarding.

## Consequences

- Climbers with stable natural hand dominance (~10–12%) see a clean dashboard without spurious warnings.
- Warnings highlight actionable, widening load imbalances and severe asymmetries.
- Warning thresholds remain centralized and tunable in `backend/analytics.py`.
