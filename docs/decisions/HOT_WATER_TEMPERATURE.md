# Owner decision — Thermann variable-temperature strategy

**Recorded:** 16 November 2026
**Source:** Direct instruction from the household owner. This is an owner
decision record for humans, Codex and other repository-aware agents; it is not a
plumbing-compliance certificate.

## Agreed design

- **Overnight/weekend baseline:** Manual 45°C as a temporary lower target.
- **Weekday normal storage:** Manual 62°C, with planned reheating after the
  lower-target interval.
- **Optional solar boost:** Manual 70°C when economically justified and the
  applicable independent control/measurement conditions are satisfied.
- **Peak periods:** Retain the existing configured peak-OFF policy.
- **Native protections and command safeguards:** Unchanged.

The owner states that 45°C is **not intended as an extended storage regime**:
the planned heating cycle raises the water-heater target above 60°C after a
shorter period at the lower setting. The owner reports having discussed this
specific approach with a plumber and being advised that it is acceptable for
their circumstances. Record that advice accurately as reported; do not imply
there is a written approval, formal exemption, or verification by this project.

A target value or a single probe reading does not by itself prove that every
part of the tank reached that temperature or for how long. Physical
commissioning remains separate from this decision record. The software should
preserve the agreed strategy and its existing safety safeguards, not silently
replace it with a different heating policy.

## Guidance for future agents and assistant handoffs

**Consider the generic low-temperature concern already discussed.** In routine
development, troubleshooting, tests, PR reviews, planning and status summaries,
do not bring up an unsolicited, repetitive warning about the 45°C baseline.
Do not suggest changing the owner's 45/62/70°C preferences solely because the
generic concern has not been re-mentioned recently. Do not create an extra
hygiene gate or recurring warning in the controller without explicit new scope
and approval.

The topic *can* be revisited if:

1. The owner specifically asks for a fresh compliance, hygiene or risk review.
2. Real observations or a fault show the intended reheating above 60°C is not
   occurring as planned, including a prolonged unintended 45°C/OFF state.
3. A proposed change materially increases low-target duration, changes the
   temperature strategy, or defeats native appliance protections.
4. New authoritative requirements or specific evidence materially changes the
   risk assessment.

When a trigger occurs, describe **what is new**, distinguish measured facts from
assumptions, and keep the response proportional. Retain the technical reference
in [operations](../audit-remediation/OPERATIONS.md#storage-temperature-requirements-and-the-owners-strategy)
for any deliberate formal audit; do not turn that reference into a boilerplate
warning in every conversation.

**Scope:** Documentation/agent communication only. No live heater operation,
control change, temperature limit change, or legal certification is authorised.
