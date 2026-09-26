import json
import unittest
from unittest.mock import patch

from interaction_contracts import TraceFormatError, audit


def snapshot(*ids, thread="t", revision="r1", **extra):
    return {"type": "snapshot", "thread_id": thread, "revision": revision,
            "pending": [{"id": item} for item in ids], **extra}


def resume(*, thread="t", revision="r1", **payload):
    return {"type": "resume", "thread_id": thread, "revision": revision, **payload}


def context(revision, thread="t"):
    return {"type": "context", "thread_id": thread, "revision": revision}


def codes(report):
    return [finding.code for finding in report.findings]


class AuditTests(unittest.TestCase):
    def test_empty_and_snapshot_only_are_inconclusive(self):
        for events in ([], [snapshot()], [snapshot("q")], [context("r1")]):
            with self.subTest(events=events):
                report = audit(events)
                self.assertEqual(report.status, "inconclusive")
                self.assertFalse(report.ok)

    def test_scalar_falsy_payloads_are_valid(self):
        for value in (False, None, 0, "", [], {}):
            with self.subTest(value=value):
                report = audit([snapshot("q"), resume(value=value)])
                self.assertTrue(report.ok)
                self.assertEqual(report.counts["pending_requests"], 0)

    def test_nested_duplicate_observations_are_one_distinct_request(self):
        report = audit([snapshot("q", "q"), snapshot("q"), resume(value=True)])
        self.assertTrue(report.ok)
        self.assertIn("DUPLICATE_REQUEST_ID", codes(report))
        self.assertEqual(report.counts["warnings"], 1)

    def test_ambiguous_resume_never_consumes_pending(self):
        report = audit([snapshot("left", "right"), resume(value=True),
                        resume(answers={"right": False, "left": None})])
        self.assertEqual(report.status, "fail")
        self.assertEqual(codes(report), ["AMBIGUOUS_RESUME"])
        self.assertEqual(report.counts["accepted_resumes"], 1)
        self.assertEqual(report.counts["pending_requests"], 0)

    def test_mapped_subset_consumes_only_selected_request(self):
        report = audit([snapshot("a", "b"), resume(answers={"a": False}),
                        resume(value=None)])
        self.assertTrue(report.ok)
        self.assertEqual(report.counts["accepted_resumes"], 2)

    def test_invalid_mapping_is_atomic(self):
        report = audit([snapshot("a", "b"), resume(answers={"a": True, "unknown": False}),
                        resume(answers={"a": False}), resume(value=None)])
        self.assertEqual(codes(report), ["UNKNOWN_REQUEST"])
        self.assertEqual(report.counts["accepted_resumes"], 2)

    def test_repeated_mapped_reply_is_unknown_even_when_pending_empty(self):
        report = audit([snapshot("q"), resume(answers={"q": 1}), resume(answers={"q": 2})])
        self.assertEqual(codes(report), ["UNKNOWN_REQUEST"])

    def test_no_pending_scalar(self):
        self.assertEqual(codes(audit([snapshot(), resume(value=None)])), ["NO_PENDING_REQUEST"])

    def test_unknown_thread_does_not_inherit_another_threads_snapshot(self):
        report = audit([snapshot("q", thread="a"), resume(thread="b", answers={"q": 1}),
                        resume(thread="a", answers={"q": 2})])
        self.assertEqual(codes(report), ["NO_CURRENT_SNAPSHOT"])
        self.assertEqual(report.counts["accepted_resumes"], 1)

    def test_interleaved_threads_can_share_request_ids(self):
        report = audit([snapshot("q", thread="a"), snapshot("q", thread="b", revision="v2"),
                        resume(thread="b", revision="v2", answers={"q": "b"}),
                        resume(thread="a", answers={"q": "a"})])
        self.assertTrue(report.ok)
        self.assertEqual(report.counts["threads"], 2)

    def test_stale_resume_is_atomic(self):
        report = audit([snapshot("q"), resume(revision="old", answers={"q": True}), resume(value=False)])
        self.assertEqual(codes(report), ["STALE_REVISION"])
        self.assertEqual(report.counts["accepted_resumes"], 1)

    def test_context_invalidates_snapshot_and_stale_snapshot_cannot_roll_back(self):
        report = audit([snapshot("old"), context("r2"), snapshot("old"),
                        resume(answers={"old": True}),
                        resume(revision="r2", value=True),
                        snapshot("fresh", revision="r2"), resume(revision="r2", value=False)])
        self.assertEqual(codes(report), ["STALE_SNAPSHOT", "STALE_REVISION", "NO_CURRENT_SNAPSHOT"])
        self.assertEqual(report.counts["accepted_resumes"], 1)
        self.assertEqual(report.counts["pending_requests"], 0)

    def test_same_context_does_not_invalidate_snapshot(self):
        self.assertTrue(audit([snapshot("q"), context("r1"), resume(value=True)]).ok)

    def test_fresh_snapshot_is_authoritative(self):
        report = audit([snapshot("removed", "retained"), snapshot("retained", "new"),
                        resume(answers={"new": True}), snapshot("retained"), resume(value=True)])
        self.assertTrue(report.ok)

    def test_consumed_request_cannot_be_resurrected_by_snapshot(self):
        report = audit([snapshot("q"), resume(value=True), snapshot("q"), resume(value=True)])
        self.assertEqual(report.status, "fail")
        self.assertEqual(codes(report), ["RESOLVED_REQUEST_REAPPEARED", "NO_PENDING_REQUEST"])
        self.assertEqual(report.counts["accepted_resumes"], 1)

    def test_snapshot_with_resolved_id_is_rejected_atomically(self):
        report = audit([snapshot("resolved", "retained"), resume(answers={"resolved": True}),
                        snapshot("resolved", "new"), resume(answers={"new": True}),
                        resume(answers={"retained": True})])
        self.assertEqual(codes(report), ["RESOLVED_REQUEST_REAPPEARED", "UNKNOWN_REQUEST"])
        self.assertEqual(report.counts["accepted_resumes"], 2)

    def test_request_id_can_recur_in_a_fresh_interaction_epoch(self):
        report = audit([snapshot("q"), resume(value=True), context("r2"),
                        snapshot("q", revision="r2"), resume(revision="r2", value=False)])
        self.assertTrue(report.ok)
        self.assertEqual(report.counts["accepted_resumes"], 2)

    def test_context_cannot_reuse_a_departed_revision(self):
        report = audit([snapshot("q"), resume(value=True), context("r2"),
                        snapshot("current", revision="r2"), context("r1"), snapshot("q"),
                        resume(value=True), resume(revision="r2", value=False)])
        self.assertEqual(codes(report), ["REUSED_REVISION", "STALE_SNAPSHOT", "STALE_REVISION"])
        self.assertEqual(report.counts["accepted_resumes"], 2)

    def test_departed_empty_context_revision_cannot_be_reused(self):
        report = audit([context("r1"), context("r2"), context("r1"),
                        snapshot("q", revision="r2"), resume(revision="r2", value=True)])
        self.assertEqual(codes(report), ["REUSED_REVISION"])
        self.assertEqual(report.counts["accepted_resumes"], 1)

    def test_revision_registry_is_scoped_to_thread(self):
        report = audit([context("r1", thread="a"), context("r2", thread="a"),
                        snapshot("q", thread="b"), resume(thread="b", value=True)])
        self.assertTrue(report.ok)

    def test_conflicting_duplicate_keys_reject_entire_snapshot(self):
        conflicting = snapshot()
        conflicting["pending"] = [{"id": "q", "key": "a"}, {"id": "q", "key": "b"}]
        report = audit([snapshot("retained"), conflicting, resume(value=True)])
        self.assertEqual(codes(report), ["CONFLICTING_REQUEST_KEY"])
        self.assertEqual(report.counts["accepted_resumes"], 1)

    def test_invalid_first_snapshot_does_not_establish_revision(self):
        conflicting = snapshot()
        conflicting["pending"] = [{"id": "q", "key": "a"}, {"id": "q", "key": "b"}]
        report = audit([conflicting, snapshot("q", revision="r2"), resume(revision="r2", value=True)])
        self.assertEqual(codes(report), ["CONFLICTING_REQUEST_KEY"])
        self.assertEqual(report.counts["accepted_resumes"], 1)

    def test_missing_key_merges_explicit_key_in_either_observation_order(self):
        for observations in ([{"id": "q"}, {"id": "q", "key": "a"}],
                             [{"id": "q", "key": "a"}, {"id": "q"}]):
            with self.subTest(observations=observations):
                event = snapshot()
                event["pending"] = [*observations, {"id": "other", "key": "a"}]
                report = audit([event, resume(answers={"q": True, "other": False})])
                self.assertTrue(report.ok)
                self.assertEqual(codes(report), ["DUPLICATE_REQUEST_ID", "DUPLICATE_PENDING_KEY"])

    def test_duplicate_logical_key_is_only_checked_when_explicit(self):
        event = snapshot("q1", "q2")
        self.assertNotIn("DUPLICATE_PENDING_KEY", codes(audit([event])))
        for item in event["pending"]:
            item["key"] = "same-decision"
        report = audit([event, resume(answers={"q1": True, "q2": False})])
        self.assertIn("DUPLICATE_PENDING_KEY", codes(report))
        self.assertTrue(report.ok)

    def test_duplicate_event_is_skipped_without_consuming_or_restoring(self):
        first = snapshot("q", event_id="snap")
        report = audit([first, resume(value=True), first, resume(value=False)])
        self.assertEqual(codes(report), ["DUPLICATE_EVENT_ID", "NO_PENDING_REQUEST"])
        self.assertEqual(report.counts["accepted_resumes"], 1)

    def test_duplicate_resume_event_has_own_error(self):
        answer = resume(value=True, event_id="answer")
        report = audit([snapshot("q"), answer, answer])
        self.assertEqual(codes(report), ["DUPLICATE_EVENT_ID"])
        self.assertEqual(report.counts["rejected_resumes"], 1)

    def test_pending_at_end_is_informational(self):
        report = audit([snapshot("a", "b"), resume(answers={"a": None})])
        self.assertTrue(report.ok)
        self.assertEqual(codes(report), ["PENDING_AT_END"])
        self.assertIsNone(report.findings[0].event_index)

    def test_generator_consumed_once_and_report_json_serializable(self):
        report = audit(event for event in [snapshot("q"), resume(value={"nested": [False, None]})])
        decoded = json.loads(json.dumps(report.to_dict()))
        self.assertEqual(decoded["schema_version"], "1")
        self.assertEqual(decoded["counts"]["events"], 2)

    def test_metadata_is_ignored_and_payload_not_exposed(self):
        secret = "private answer text"
        report = audit([snapshot("q", metadata={"source": secret}), resume(value=secret)])
        self.assertNotIn(secret, json.dumps(report.to_dict()))

    def test_malformed_schema_is_not_a_contract_finding(self):
        cases = [None, [], {}, {"type": "unknown"}, snapshot(True), snapshot(""), snapshot(" "),
                 snapshot("q", revision=True), snapshot("q", thread=False),
                 {"type": "snapshot", "thread_id": "t", "pending": []},
                 {"type": "snapshot", "thread_id": "t", "revision": "r1", "pending": {}},
                 snapshot("q", event_id=False), snapshot("q", revision=""),
                 resume(), resume(value=None, answers={"q": True}), resume(answers={}),
                 resume(answers={False: 1}), resume(answers={"": 1}), resume(answers=[]),
                 resume(value=float("nan")), resume(value=float("inf")),
                 resume(value={1: "bad key"}), resume(value=(1, 2)),
                 snapshot("q", unexpected=True), snapshot("q", metadata=[])]
        for event in cases:
            with self.subTest(event=event):
                with self.assertRaises(TraceFormatError):
                    audit([event])

    def test_malformed_pending_key_and_unknown_pending_field(self):
        for request in ({"id": "q", "key": False}, {"id": "q", "key": ""},
                        {"id": "q", "value": "unrecognized"}):
            event = snapshot()
            event["pending"] = [request]
            with self.assertRaises(TraceFormatError):
                audit([event])

    def test_non_iterable_and_cyclic_payload(self):
        for invalid_trace in (None, {}, "", b"", snapshot("q")):
            with self.subTest(invalid_trace=invalid_trace):
                with self.assertRaises(TraceFormatError):
                    audit(invalid_trace)
        value = []
        value.append(value)
        with self.assertRaises(TraceFormatError):
            audit([resume(value=value)])

    def test_json_payload_nesting_is_bounded(self):
        value = None
        for _ in range(128):
            value = [value]
        self.assertTrue(audit([snapshot("q"), resume(value=value)]).ok)
        with self.assertRaisesRegex(TraceFormatError, "nesting depth"):
            audit([resume(value=[value])])
        for _ in range(1500):
            value = {"nested": value}
        with self.assertRaises(TraceFormatError):
            audit([resume(value=value)])

    def test_recursion_error_is_converted_to_trace_format_error(self):
        with patch("interaction_contracts.core._validate", side_effect=RecursionError):
            with self.assertRaisesRegex(TraceFormatError, "recursion limit"):
                audit([snapshot("q")])


if __name__ == "__main__":
    unittest.main()
