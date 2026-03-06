import ast
import sys
import types
import unittest
from collections import defaultdict
from pathlib import Path

sys.modules.setdefault("requests", types.ModuleType("requests"))
yaml_stub = sys.modules.setdefault("yaml", types.ModuleType("yaml"))
if not hasattr(yaml_stub, "safe_load"):
    yaml_stub.safe_load = lambda *_args, **_kwargs: None
if not hasattr(yaml_stub, "YAMLError"):
    yaml_stub.YAMLError = Exception

from bug_audit_system import (
    BugCandidate,
    DEFAULT_TITLE_TEMPLATE,
    ProofArtifact,
    choose_inline_proof_artifact,
    default_submission_labels,
    evaluate_submission_candidate,
    format_issue_title,
    matched_validated_video_class,
    normalize_title_template,
    render_proof_section,
)


ROOT = Path(__file__).resolve().parent
DETECTORS_DIR = ROOT / "detectors"
ALLOWED_DUPLICATE_FINDING_IDS = {
    "titlebar-f5-pause-glyph-mismatch",
}


def make_candidate(finding_id: str, title: str, description: str) -> BugCandidate:
    return BugCandidate(
        title=title,
        description=description,
        reproduction_steps=["Open Cortex IDE.", "Reproduce the visible GUI behavior."],
        impact="User-visible workflow regression.",
        native_gui="Cortex IDE",
        proof_artifacts=[],
        prompt_id="test",
        prompt_text="test prompt",
        severity="medium",
        raw={
            "finding_id": finding_id,
            "actual_behavior": description,
        },
    )


class SubmissionQualityGateTests(unittest.TestCase):
    def test_blocks_historically_rejected_families(self) -> None:
        rejected = {
            "dashboard-activity-tab-renders-empty-sidebar": (
                "Dashboard activity icon opens a sidebar tab with no rendered panel",
                "Dashboard tab opens an empty sidebar frame instead of a rendered panel.",
            ),
            "roadmap-activity-tab-renders-empty-sidebar": (
                "Roadmap activity icon opens a sidebar tab with no rendered panel",
                "Roadmap tab opens an empty sidebar frame instead of a rendered panel.",
            ),
            "quickaccess-percent-provider-unreachable": (
                "Quick Access Help advertises '%' file-text search, but '%' provider is never registered",
                "Quick Access help advertises a percent prefix that the active router does not register.",
            ),
            "quickaccess-help-query-ignored-no-filtering": (
                "Quick Access '?' help ignores typed query and always returns full prefix list",
                "Help provider ignores typed query text and always returns the full prefix list.",
            ),
            "quickopen-question-prefix-routed-to-files": (
                "Ctrl+P `?` prefix is routed to file search instead of Quick Access Help provider",
                "Ctrl+P stays in file-search mode for question-mark prefixes.",
            ),
            "quickchat-open-full-chat-event-unhandled": (
                "Quick Chat 'Open in full chat' control closes overlay but never opens full chat",
                "Open in full chat closes quick chat without opening the full chat surface.",
            ),
            "worktree-open-new-window-event-unhandled": (
                "Worktree 'Open in New Window' action is a no-op because its command event is never handled",
                "Open in New Window dispatches an unhandled event and does nothing.",
            ),
        }

        for finding_id, (title, description) in rejected.items():
            with self.subTest(finding_id=finding_id):
                allowed, reason, _score = evaluate_submission_candidate(
                    make_candidate(finding_id, title, description)
                )
                self.assertFalse(allowed)
                self.assertIn(
                    reason,
                    {
                        f"unvalidated_video_family:{finding_id}",
                        f"blocked_finding_id:{finding_id}",
                    },
                )

    def test_allows_validated_routing_loading_class(self) -> None:
        candidate = make_candidate(
            "issue-provider-unreachable",
            "Quick Access advertises 'issue' command but never registers provider",
            "The visible Quick Access help entry exists, but the GUI router never registers the issue provider.",
        )
        self.assertEqual(matched_validated_video_class(candidate), "routing_loading")
        allowed, reason, _score = evaluate_submission_candidate(candidate)
        self.assertTrue(allowed, reason)
        self.assertEqual(reason, "passed")

    def test_allows_validated_visible_no_op_class(self) -> None:
        candidate = make_candidate(
            "new-terminal-export-button-no-op",
            "Export profiling data button doesn't work",
            "The visible Export action is clickable but does nothing after the user activates it.",
        )
        self.assertEqual(matched_validated_video_class(candidate), "visible_no_op")
        allowed, reason, score = evaluate_submission_candidate(candidate)
        self.assertTrue(allowed, reason)
        self.assertEqual(reason, "passed")
        self.assertGreaterEqual(score, 1)

    def test_allows_validated_modal_focus_class(self) -> None:
        candidate = make_candidate(
            "send-feedback-no-focus-trap",
            "Send Feedback dialog has no focus trap",
            "Tab key moves focus to background controls and Escape key does not close the modal reliably.",
        )
        self.assertEqual(matched_validated_video_class(candidate), "modal_focus_escape")
        allowed, reason, _score = evaluate_submission_candidate(candidate)
        self.assertTrue(allowed, reason)
        self.assertEqual(reason, "passed")

    def test_keeps_specific_low_confidence_findings_blocked(self) -> None:
        candidate = make_candidate(
            "worktree-open-new-window-event-unhandled",
            "Worktree Open in New Window action is a no-op",
            "Open in New Window dispatches an event but does nothing after the user clicks it.",
        )
        self.assertEqual(matched_validated_video_class(candidate), "visible_no_op")
        allowed, reason, _score = evaluate_submission_candidate(candidate)
        self.assertFalse(allowed)
        self.assertEqual(reason, "blocked_finding_id:worktree-open-new-window-event-unhandled")

    def test_allows_recently_validated_families(self) -> None:
        validated = {
            "quickaccess-editor-mru-provider-unreachable": (
                "Quick Access has an 'edt mru ' provider implementation, but router never registers it",
                "Quick Access provider exists, but the router never registers the edt mru prefix.",
            ),
            "quickaccess-term-new-terminal-query-no-results": (
                "Ctrl+P Quick Open ignores `term ` prefix, making terminal quick-access flow unreachable",
                "Ctrl+P remains in file-search mode and never routes term-prefixed queries to terminal results.",
            ),
            "editor-loading-stuck-terminalgrouptabs-file-open": (
                "Opening `src/components/TerminalGroupTabs.tsx` can leave editor stuck on `Loading editor...`",
                "Opening TerminalGroupTabs leaves the editor stuck on Loading editor instead of rendering content.",
            ),
        }

        for finding_id, (title, description) in validated.items():
            with self.subTest(finding_id=finding_id):
                allowed, reason, score = evaluate_submission_candidate(
                    make_candidate(finding_id, title, description)
                )
                self.assertTrue(allowed, reason)
                self.assertEqual(reason, "passed")
                self.assertGreaterEqual(score, 1)


class DetectorMetadataTests(unittest.TestCase):
    def test_detector_finding_ids_are_unique(self) -> None:
        finding_ids: dict[str, list[str]] = defaultdict(list)

        for path in sorted(DETECTORS_DIR.glob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(module):
                if not isinstance(node, ast.Assign):
                    continue
                if len(node.targets) != 1:
                    continue
                target = node.targets[0]
                if not isinstance(target, ast.Name) or target.id != "finding_id":
                    continue
                if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                    continue
                finding_ids[node.value.value].append(path.name)

        unexpected_duplicates = {
            finding_id: paths
            for finding_id, paths in finding_ids.items()
            if len(paths) > 1 and finding_id not in ALLOWED_DUPLICATE_FINDING_IDS
        }
        self.assertFalse(unexpected_duplicates, unexpected_duplicates)


class SubmissionMetadataTests(unittest.TestCase):
    def test_bounty_challenge_defaults_to_bug_and_ide_labels(self) -> None:
        self.assertEqual(
            default_submission_labels("PlatformNetwork/bounty-challenge"),
            ["bug", "ide"],
        )

    def test_non_bounty_repo_has_no_forced_labels(self) -> None:
        self.assertEqual(
            default_submission_labels("owner/other-repo"),
            [],
        )

    def test_old_bug_alpha_template_is_normalized(self) -> None:
        self.assertEqual(
            normalize_title_template("[Bug][alpha]{title}"),
            DEFAULT_TITLE_TEMPLATE,
        )

    def test_old_bug_alpha_title_is_rendered_in_canonical_form(self) -> None:
        self.assertEqual(
            format_issue_title("[Bug][alpha]Quick Open fails", "[Bug][alpha]{title}"),
            "[BUG] [alpha] Quick Open fails",
        )


class StrictVideoProofTests(unittest.TestCase):
    def test_choose_inline_proof_artifact_prefers_real_video(self) -> None:
        candidate = make_candidate(
            "quickaccess-term-new-terminal-query-no-results",
            "Ctrl+P Quick Open ignores `term ` prefix, making terminal quick-access flow unreachable",
            "Ctrl+P remains in file-search mode and never routes term-prefixed queries to terminal results.",
        )
        artifacts = [
            ProofArtifact(
                source="quickaccess-term-new-terminal-query-no-results.png",
                public_url="https://example.com/quickaccess-term-new-terminal-query-no-results.png",
                media_type="image",
                sha256=None,
                backup_url=None,
            ),
            ProofArtifact(
                source="quickaccess-term-new-terminal-query-no-results.mp4",
                public_url="https://example.com/quickaccess-term-new-terminal-query-no-results.mp4",
                media_type="video",
                sha256=None,
                backup_url=None,
            ),
            ProofArtifact(
                source="quickaccess-term-new-terminal-query-no-results.cursor.mp4",
                public_url="https://example.com/quickaccess-term-new-terminal-query-no-results.cursor.mp4",
                media_type="video",
                sha256=None,
                backup_url=None,
            ),
        ]

        selected = choose_inline_proof_artifact(candidate, artifacts)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.media_type, "video")
        self.assertTrue(selected.public_url.endswith(".mp4"))
        self.assertFalse(selected.public_url.endswith(".cursor.mp4"))

    def test_render_proof_section_omits_image_markup_in_strict_video_mode(self) -> None:
        candidate = make_candidate(
            "quickaccess-term-new-terminal-query-no-results",
            "Ctrl+P Quick Open ignores `term ` prefix, making terminal quick-access flow unreachable",
            "Ctrl+P remains in file-search mode and never routes term-prefixed queries to terminal results.",
        )
        artifacts = [
            ProofArtifact(
                source="quickaccess-term-new-terminal-query-no-results.png",
                public_url="https://example.com/quickaccess-term-new-terminal-query-no-results.png",
                media_type="image",
                sha256=None,
                backup_url=None,
            ),
            ProofArtifact(
                source="quickaccess-term-new-terminal-query-no-results.mp4",
                public_url="https://example.com/quickaccess-term-new-terminal-query-no-results.mp4",
                media_type="video",
                sha256=None,
                backup_url="https://example.com/quickaccess-term-new-terminal-query-no-results.gist",
            ),
        ]

        rendered = render_proof_section(candidate, artifacts, "Cortex IDE")
        self.assertNotIn("![", rendered)
        self.assertIn("<video", rendered)
        self.assertIn("[Video proof](", rendered)


if __name__ == "__main__":
    unittest.main()
