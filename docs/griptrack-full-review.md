# GripTrack — Full Critical Review

*Review of `technical-guide.md` and `product-overview.md`, snapshot 2026-07-08 (main @ d89fbd9). Supersedes the earlier question-driven review; this version covers the full breadth a design/architecture grill should.*

## 1. Product vision and audience

GripTrack has an unusually crisp implicit thesis: finger strength is a per-hand, per-grip, per-edge quantity, and a training tool should model it that way or not bother. That thesis is correct and is the product. Everything good downstream — CurrentMax semantics, per-combination charts, the future asymmetry work — follows from it, and almost no competitor shares it.

The audience is currently "the owner and invited friends," and the documents are honest about that. The unresolved strategic question is which of three futures the roadmap serves: a personal instrument that stays small, a public product, or a coach-mediated tool. These pull in different directions (a coach view changes the data-isolation story; a public product demands the whole launch apparatus in §12). The review's strongest strategic recommendation is to decide this explicitly, because several open threads — benchmarking, AI features, open signup — are only rational under one of the three.

## 2. Fit with the climbing community

Block pulls / no-hangs are where evidence-oriented finger training has moved: better load control, unilateral data, lower injury exposure than board hangs. GripTrack rides that shift. Its plate-inventory rounding is the kind of detail that earns trust — a suggestion you can physically load is a suggestion you follow — and the autosave, no-submit session flow matches real gym conditions (interrupted, one-handed, chalky).

What it doesn't serve: hangboard repeaters and two-hand protocols, campus work, prescribed-plan users, and coaches. Also unserved: the measurement-first crowd, who have largely standardized on Bluetooth load cells (Tindeq Progressor and clones). That last gap matters most, because it's where the community's center of gravity is heading — see §17.

## 3. Competitive landscape and differentiation

Crimpd and Lattice's app are protocol libraries plus plans; KletterRetter and Beastmaker are board-centric; Tindeq companion apps measure force but barely manage training over time. GripTrack's differentiators — combination keying, CurrentMax, plate rounding — are real but invisible on a feature-comparison grid. Three things would make the differentiation legible: force-gauge ingestion (§17), asymmetry analytics (already sequenced, correctly), and eventually opt-in anonymized benchmarking, which is the compounding moat the Lattice dataset proved but which depends on unit normalization (§6) and consent design. Until then, the honest positioning is depth-of-model, not breadth-of-features.

## 4. Training-science critique

This is where the review has the most substantive findings, because the app encodes training theory in code and some of the encodings have consequences.

**TrainingVolume conflates intensity and volume.** Σ(weight×reps) rewards a 5×10 light session and a 3×5 heavy session interchangeably. For max-strength work — the stated purpose — intensity relative to max is the primary driver, and a user progressing intensity while trimming sets can trip the plateau flag mid-progress, while a user inflating reps at low weight looks like they're improving. At minimum, tracking average intensity (mean set weight ÷ CurrentMax at session date — the `as_of` machinery already exists for exactly this) alongside tonnage would let the plateau logic look at both.

**CurrentMax systematically underestimates after training blocks.** A work set of 5 reps at weight X implies a single-rep max meaningfully above X (any rep-max formula puts it 15%+ higher), yet CurrentMax only rises when a single work set's weight exceeds the old max. The consequence: ramp and work-set suggestions are computed as percentages of an underestimate, so the app's prescriptions drift conservative between formal tests. Conservative is the right direction for finger safety, but it should be a documented, deliberate bias — and it strengthens the case for gentle retest nudges when work-set history implies the max has moved.

**RPE is collected and used for nothing.** It appears in `work_sets` and in no analytics, no suggestion, no warning. Dead data erodes user trust ("why am I entering this?") and it happens to be the single best input for the roadmap's progression suggestions and a far better overtraining signal than the current volume-spike heuristic. Either wire it in (§18, Tier 1) or stop collecting it.

**The overtraining warning has a scoping problem.** It's computed per combination, but connective tissue doesn't care which grip loaded it. A user rotating grips daily can spike total finger load dramatically while every per-combination series looks calm. A cross-combination aggregate load signal (in canonical units — another cost of ADR-0003, §6) is needed before the injury-risk guardian this heuristic is described as prototyping.

**There is no way to log the thing the injury guardian needs.** No pain/tweak/niggle logging, no injury events, no deload annotation. The planned guardian has no ground-truth signal to learn from or even correlate against, and planned deload weeks will misfire the plateau flag with no way for the user to say "this was intentional." A minimal pain-and-deload annotation on sessions is small, and it's the prerequisite for every safety ambition in the roadmap.

**No rest tracking within sessions and no session duration.** The between-set rest timer is already planned; when it lands, its data should be stored, because between-set rest is a controlled variable in every serious protocol and it makes the "shorter-than-typical rest" half of the overtraining heuristic measurable within sessions, not just between them.

## 5. Statistics and analytics rigor

The strength-vs-grade correlation reports Pearson r from as few as 3 points. At n=3 the confidence interval spans essentially the whole [-1, 1] range; reporting a number there is decoration, not analysis. Raise the floor (n≥8–10) or display the interval. Two further issues: V-grades are ordinal, not interval — Spearman is the defensible choice — and strength gains lead grade gains by weeks-to-months, so same-date pairing attenuates the correlation the analysis is framed against. None of this is hard to fix and all of it matters if the feature is "framed against published research," because users will compare.

Also: sport climbs are logged and then never analyzed by anything. Collecting data with no consumer is a quiet trust leak — either exclude sport from logging scope or give it a home (even just appearing in history filters and a sends-over-time view).

## 6. Data-model critique

**The combination key breaks for pinch.** `(hand, grip_type_id, edge_mm)` is the app's atom, and pinch — in the starter grip list — has no edge depth; a pinch block has width. Whatever users currently enter in `edge_mm` for pinch is a fiction that pollutes the keying. Options: a nullable dimension with per-grip semantics ("edge depth" vs "block width"), or a per-grip flag for whether the dimension applies. Small schema change now; annoying data-cleanup later.

**One session per user+date forbids two-a-days and ignores timezones.** Morning/evening double sessions are standard in structured training blocks and are currently unrepresentable — they silently merge, corrupting volume, rest-gap, and plateau math. Separately, nothing in either document says whose date a session gets: server UTC dates will split or merge sessions for anyone training late or traveling. A `started_at` timestamp plus a user timezone (or client-supplied local date) fixes both; the unique constraint should become (user, started_at-day, sequence) or just drop the one-per-day assumption.

**Sessions have no notes field.** Climbs do. Training sessions — where "left ring finger felt tweaky on set 2" lives — don't. This is also where §4's pain/deload annotation belongs.

**Free-text grades are pragmatic but leaky.** Anything outside V/Font silently drops out of the correlation. A parse-and-normalize layer (store raw text plus a parsed canonical grade, flag unparsed entries visibly) preserves the ADR's flexibility while stopping silent exclusion. The planned grade-conversion matrix should land as this layer, not as a lookup table bolted onto analytics.

**ADR-0003 (native-unit storage) has a compounding deferred cost.** Correct for plate loadability, but every cross-user or cross-combination feature now on the roadmap — benchmarking, aggregate load (§4), threshold calibration — needs read-time canonical conversion. Record the IOU; also note that "unit fixed at signup" will eventually need a migration story for users who change countries or gyms.

## 7. UX and onboarding

The session-logging flow is the app's UX high point and the docs know it. The weak points are at the edges:

**Cold start is empty.** A new user lands on an empty dashboard, an unexplained plate inventory, and a max-test page full of domain jargon. There's no first-run sequence ("test one combination, log one session, see your first chart") and no in-app explanation of what CurrentMax means or why the app is asking for edge sizes. For an invited-friends audience the owner is the onboarding; for anything larger this is the first thing to build.

**Session estimates re-ask every session for untested combos.** Deliberate and defensible (estimates must never masquerade as data), but from the user's chair it's the app refusing to remember something they told it. A gentle "you've estimated this combo 3 times — do a guided test?" converts the friction into the behavior the design wants.

**No undo affordances beyond set deletion.** Append-only max tests are a sound data policy, but a typo'd max test (fat-fingered 80 instead of 30) permanently poisons CurrentMax with no user-visible remedy. An admin- or self-service "void this test" flag preserves append-only history while restoring correctness.

**No data export.** Users' training history is trapped. CSV export is a day of work, a trust signal, a GDPR requirement later anyway, and the escape hatch that paradoxically makes people comfortable committing to a small tool.

**Small frictions worth a UX pass:** RPE in 0.5 steps needs a decent mobile input (steppers, not a bare number field); the greeting-by-email-prefix is charming until someone's email is `hotstuff69@`; the rest-timer feature, when built, needs a wake lock and a notification/audio strategy or it will fail exactly when phones lock between sets.

## 8. Accessibility and inclusivity

Nothing in either document mentions accessibility. Concrete gaps: server-rendered SVG charts need titles/ARIA descriptions or they're invisible to screen readers; plateau/overtraining states must not be color-only; the light/dark palettes should be checked for contrast and for common color-vision deficiencies; and the claimed large touch targets should be verified against the 44px-minimum guideline during the pending phone-testing pass. None of this is expensive at current page count; all of it is expensive to retrofit at fifty templates.

## 9. Security review

The foundation is unusually solid for a hobby-scale app — bcrypt directly, timing-equalized login, per-route user scoping with isolation tests, input bounds as a house rule, invite-only registration killing the signup attack surface. Findings, in rough priority order:

**Session revocation doesn't exist.** Signed cookies mean the admin password reset (the app's only recovery path) presumably leaves the old session valid. A stolen session survives the remedy for a stolen password. Either add a per-user session-generation counter checked in `current_user`, or document the residual risk. This deserves a test either way.

**CSP `unsafe-inline` largely defeats the CSP.** htmx supports nonce-based operation; moving the inline glue to nonced scripts is contained work and should precede any audience growth.

**Rate limiting covers only login.** Invite redemption (`/register` with a code) is brute-forceable at whatever entropy the codes carry — the documents don't state their length. The guided-test and chart endpoints are authenticated but expensive (matplotlib render per hit), making them a low-effort resource-exhaustion vector for any valid account. A cheap global per-session request ceiling closes both.

**No dependency hygiene in CI.** No mention of `pip-audit`/Dependabot or lockfile scanning. The passlib note shows the maintainer tracks ecosystem rot manually; automate it.

**Smaller items:** session cookie lifetime/rotation unspecified; no audit trail for admin actions (invite creation, password resets) — one append-only table, trivially cheap, disproportionately valuable the day something looks wrong; backup bucket credentials will be long-lived S3 keys — scope them to the one bucket; no 2FA, acceptable at invite-only scale, required conversation before public.

## 10. Privacy and legal

Bodyweight series plus training-load history is health-adjacent data; under GDPR-style regimes, arguably health data outright. Public launch therefore requires not just a privacy policy but export, deletion, and a retention position (§7 export doubles here). The overtraining warning and the future injury guardian make wellness claims; they need explicit non-medical disclaimer language in-product, not just in docs. And the benchmarking ambition (§3) must be consent-first from its first design sketch — retrofitting consent onto aggregated health-adjacent data is how small projects get into large trouble.

## 11. Performance and scalability

The htmx architecture keeps page weight and client complexity near zero — genuinely good. Three notes: matplotlib+pandas per dashboard hit with `no-store` means every view pays full render; cache keyed on (user, combo, latest-session-id) or hand-roll the SVG and drop two heavyweight dependencies. SQLite is right and stays right for a long time provided WAL mode and `busy_timeout` are set — neither is mentioned, and autosave means many small writes from concurrent users, which is exactly the workload where default rollback-journal SQLite starts throwing `database is locked`. Verify. Finally, the whole design (in-memory rate limiter, signed-cookie sessions, SQLite single-writer) assumes one process on one node; that's internally consistent, but it should be written down as a constraint so a future "just scale to 2 instances" doesn't silently break three subsystems.

## 12. Reliability and operations

**The backup gap is the single most urgent finding in this review.** Litestream is baked in, configured, and inert — production data exists in exactly one place, on one volume, at one vendor. Enabling replication and, critically, *rehearsing a restore* is a configuration afternoon and should precede every other line in this document.

Beyond that: no error tracking, metrics, or alerting exist anywhere in the docs — the owner finds out about breakage from users; migrations run at container boot, so a bad migration is a production crash loop with no staging environment mentioned to catch it first; deploy verification checks health and migration logs, which is good, but there's no stated rollback procedure; and the Fly→Oracle migration plan is sound on paper (the never-two-writers rule is correctly identified) but has never executed — treat it as untested code. Single region, single node is fine for the mission; just fine knowingly.

## 13. Engineering process and testing

The process discipline is a genuine strength: ADRs, migrations-with-seeds, identical scripts locally and in CI, TDD as a stated norm, docs written for review. Gaps:

**CI runs tests and migration checks but apparently no lint or type-check.** For a codebase with documented agent-facing conventions (`CLAUDE.md`) — i.e., one where AI agents contribute — ruff and mypy in CI are more important, not less: they're the guardrails that catch what a generating agent plausibly gets wrong.

**The HTTP-seam-only test philosophy is defensible but has two expensive corners.** The plate subset-sum and the analytics math carry the app's trickiest logic; property-based tests directly against those functions would catch input classes the seam only samples (adversarial inventories, degenerate variance, boundary plateaus). This isn't re-litigating the decision, it's noting where it costs most.

**Nothing exercises a real browser.** htmx behavior, the service worker lifecycle, and the CACHE_VERSION update dance are all untested outside TestClient; a handful of Playwright smoke tests (login, log a session, install-shell loads offline) would cover the app's most embarrassing failure modes. Relatedly, the CACHE_VERSION manual-bump rule is a process landmine — derive it from a content hash at build time and delete the rule.

**Bus factor is one.** Documentation quality mitigates this better than most solo projects manage, but the review should say it: every operational secret, deploy habit, and threshold rationale should live in the repo, not the owner's head. The docs suggest this is largely true; keep it true.

## 14. Architecture verdict and alternatives

The stack is right-sized and the review's job is partly to defend it against "upgrades." Postgres+SPA+managed-auth would add operational surface and remove nothing hard. The only alternative that competes on merits is local-first (client-owned replica, server as sync relay): it would solve offline logging natively and make the PWA feel instant, at the cost of sync-conflict semantics, a client build step, a large JS surface, and the loss of the clean server-side analytics and the 131-test HTTP seam. For a solo-maintained multi-user app, the current architecture is close to the minimum viable shape. The one real tension — htmx's server-rendered model versus offline interactivity — resolves at feature scope, not architecture scope (§15).

## 15. Native app? Fully offline?

Native: not now. The PWA covers install and full-screen at a fraction of two app-store pipelines. The forces that could change this are iOS-shaped: no Web Bluetooth in Safari (blocks Tindeq on iPhone) and iOS's second-class PWA treatment. Revisit when one of those blocks a committed feature; a Capacitor wrapper is the cheap middle path if it comes to that.

Fully offline: no — it forfeits multi-device, server analytics, and the backup story. The right target is issue #20's middle ground, and the existing design is accidentally excellent for it: session logging is already idempotent upserts on stable keys (session+hand+grip+edge+set_number), which is precisely what a background-sync replay queue wants. Scope: queue work-set and warmup-check POSTs in IndexedDB, replay via Background Sync, serve the two session pages from a cached snapshot (ramp weights are computed at render anyway, so they're already in the page). Offline browsing of history and dashboards can stay out of scope indefinitely. The design grill the issue asks for should mostly be about conflict edges (two devices, one session) and replay idempotency proofs — both tractable.

## 16. AI: training hints and suggested paths

Sequence beats ambition here. The dataset is a handful of users with self-described placeholder thresholds; learned models on it are noise, and finger training is the one climbing domain where bad automated advice injures people.

**Tier 1 — deterministic autoregulation (build this; don't call it AI).** Rules over existing data: all sets at target reps with RPE ≤ 7 for two consecutive sessions → suggest the smallest loadable increment (the plate module knows what that is); RPE ≥ 9 or missed reps → hold or step down; plateau flag → nudge retest or combination change; work-set history implying max drift (§4) → nudge retest. Transparent, testable at the HTTP seam, and genuinely most of a coach's value.

**Tier 2 — LLM narrative over the user's own computed facts.** "Left-hand 10 mm volume has lagged right by ~15% for three weeks; both plateau flags coincided with sub-48 h gaps." Commentary on analytics output, never generated prescription, framed exactly that way. Cheap, low-risk, feels premium.

**Tier 3 — learned models: not until population-scale, consented, unit-normalized data exists**, which means well after a public launch. The injury guardian stays a conservative heuristic with non-medical framing indefinitely; at this data volume "AI injury prediction" is a liability wearing a feature's clothes. And per §4, even the heuristic guardian is blocked on pain logging and cross-combination load — data model first, intelligence later.

## 17. Integrations and ecosystem

In rough order of leverage: **Tindeq/force-gauge ingestion** (Web Bluetooth; Android-installed-PWA first, iOS via wrapper later) — peak force, then critical-force and RFD protocols; this is the feature the combination-keyed model was unknowingly built for and the plate-tracking competitors can't follow. **CSV/JSON export** — trust, GDPR, and the spreadsheet crowd, for a day's work. **Health-platform write-out** (Apple Health / Health Connect workout entries) — nice-to-have, native-wrapper-gated. **Coach/shared views** — a real community wedge, but it reshapes the data-isolation story and belongs after the §1 strategic decision, not before.

## 18. Sustainability and cost of ownership

Current costs are near zero and the architecture protects that. If the answer to §1 is "public product," the honest accounting includes support burden (password resets are already manual admin actions — that does not scale past dozens of users), email infrastructure costs, moderation of shared features, and an on-call reality for a solo maintainer. Two alternatives deserve explicit consideration: staying deliberately small (invite-only forever, which the current design serves perfectly), or open-sourcing the app so the community self-hosts — which converts support burden into contribution surface and suits the project's documentation-heavy culture unusually well. Monetization (a small subscription for hosted accounts) is only worth designing after the strategic decision, but note that health-adjacent data plus payments raises the compliance bar of §10 further.

## 19. Consolidated risk register

In descending severity: **data loss** (backups inert — one volume failure ends the project's trust permanently; mitigation is a config afternoon); **injury liability** (wellness-flavored warnings on uncalibrated heuristics; mitigate with disclaimers now, pain-logging and conservative framing forever); **key person** (solo maintainer; mitigated by documentation, keep it that way); **platform** (iOS PWA and Bluetooth constraints gate the two most differentiating features); **silent data corruption** (one-session-per-day merging, pinch edge_mm fiction, timezone dating — all quietly poison analytics before anyone notices); **scope creep** (the roadmap contains three products; §1 again).

## 20. Roadmap recommendation

**Immediately:** enable Litestream and rehearse a restore; verify WAL + busy_timeout; complete the pending PWA phone test; add error tracking (a Sentry-class SDK is an hour); add ruff+mypy+pip-audit to CI.

**Data-model corrections (cheap now, expensive later):** session timestamps + timezone handling and multi-session days; pinch dimension semantics; session notes with pain/deload annotation; void-a-test flag; store raw+parsed grades.

**Retention:** rest timer (with stored rest data, wake lock, notifications); per-user protocol overrides; RPE wired into Tier-1 progression rules; asymmetry analytics; retest nudges.

**Differentiation:** Tindeq ingestion spike on Android PWA; issue #20 offline-sync design scoped to the replay-queue approach; grade-normalization layer; CSV export.

**Public-launch track (only if §1 says so):** email infra, open signup with abuse controls, deletion/export/legal, real domain, 2FA decision, calibrated or clearly-disclaimed thresholds, statistics fixes from §5.

**Later:** injury guardian (after pain logging + cross-combination load), coach views, opt-in benchmarking, native wrapper if iOS demands it.

## 21. Closing judgment

This is a rare project where the recorded decisions and the real pressures line up, and where the weaknesses are mostly conscious IOUs rather than accidents — the strongest possible signal in a review. The findings that the documents undersell: the backup gap is an emergency dressed as a config detail; a cluster of small data-model choices (daily-unique sessions, pinch edge depth, unused RPE, no pain logging) will quietly cap the analytics and safety ambitions if not fixed while the dataset is small; and the product's ceiling is set less by its feature list than by whether it commits to the force-measurement direction its own data model is already shaped for.
