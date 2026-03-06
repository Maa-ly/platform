# Echobt Validation Profile (Practical, Non-Bypass)

Date: 2026-03-05

This profile is derived from sampled `echobt` moderation outcomes on
`PlatformNetwork/bounty-challenge` (issues with `valid`/`invalid` labels and
`echobt` comments).

## What Causes Rejection Most Often

From a 600-issue sample (300 invalid-labeled + 300 valid-labeled with `echobt` comments):

- `duplicate`: most common rejection class by far
- `proof_not_showing_bug`: frequent hard reject language
- `no_commands_found`: repeated reject pattern for command-palette based claims
- `scope_mismatch` and `missing_steps`: rarer but still explicit reject reasons

## Enforced Policy Gates in This Repo

Implemented in code to reduce invalid submissions legitimately:

1. Strict external dedup (open + closed)
   - File: `bug_audit_system.py`
   - Behavior:
     - Checks open and closed states explicitly
     - Uses multiple hint queries (strict + relaxed)
     - Adds strict semantic overlap fallback for reworded duplicates
     - Caches search responses to reduce API churn and improve consistency

2. User-facing issue body sanitization
   - File: `bug_audit_system.py`
   - Behavior:
     - Removes code-audit style snippets/paths/evidence-line dumps from report text
     - Keeps report in user-impact + reproducible-flow format

3. Motion proof enabled by default in inline proof rendering
   - File: `bug_audit_system.py`
   - Behavior:
     - Includes inline motion evidence unless `CORTEX_INCLUDE_MOTION_PROOF=0`

4. High-risk shortcut-conflict findings disabled by default
   - File: `detectors/cortex_event_routing_detector.py`
   - Behavior:
     - Shortcut conflict findings require opt-in:
       - `CORTEX_ENABLE_SHORTCUT_CONFLICT_FINDINGS=1`
       - `CORTEX_ENABLE_AMBIGUOUS_SHORTCUT_FINDINGS=1`

5. Full GUI + reproducible-state capture safeguards
   - File: `detectors/cortex_gui_capture.py`
   - Behavior:
     - Preserves finding-specific sidebar state during workspace-open enforcement
     - Prevents state clobber that previously produced non-demonstrative captures

6. Low-confidence conflict class blocker (new)
   - File: `bug_audit_system.py`
   - Behavior:
     - Treats `invalid`, `duplicate`, and `duplicated` labels as invalid for quota math
     - Blocks known low-yield finding families before submission:
       - shortcut/keybinding collision classes
       - known weak IDs repeatedly invalidated by moderation
     - Prioritizes candidates by confidence score derived from historically validated patterns

7. Proof URL accessibility gate (new)
   - File: `bug_audit_system.py` (`ProofManager`)
   - Behavior:
     - Verifies uploaded media URLs are publicly accessible and resolve to media content
     - Fails submission early when links are inaccessible instead of posting unverifiable proof

8. Inline proof coherence tightening (new)
   - File: `bug_audit_system.py`
   - Behavior:
     - Generic finding rendering now avoids auto-including extra follow-up screenshots that may be unrelated
     - Keeps one primary screenshot + optional motion evidence to reduce incoherent attachment sets

## Operational Guidance

- Do not submit when strict dedup flags a match.
- For dynamic UI bugs, require motion evidence and visible in-GUI state transition.
- Avoid command-palette-only proofs unless the screenshot/video visibly shows the claimed condition (not just search text).
- Keep report language user-perspective first; avoid root-cause/code-audit narrative in the issue body.

## Constraint

No process can guarantee "always valid" because final triage is external and can change.
This profile maximizes acceptance probability while staying compliant.
