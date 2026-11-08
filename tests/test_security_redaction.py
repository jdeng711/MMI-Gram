"""
Regression Test Suite for Sensitive Data & Credential Redaction.

Verifies that GCS signed URLs, Google API keys, authorization tokens,
and sensitive query parameters are scrubbed from:
1. Telemetry logging and state summaries (StructuredAgentLogger)
2. Agent traces and event records
3. HumanReviewQueue disk persistence files
4. General payload sanitization
"""

import json
import tempfile
import unittest
from pathlib import Path

from mmigram.telemetry.tracer import (
    redact_sensitive_strings,
    sanitize_payload,
    StructuredAgentLogger,
    summarize_state,
)
from mmigram.review.queue import HumanReviewQueue


class TestSecurityRedaction(unittest.TestCase):
    """Test suite for security redaction rules."""

    def test_gcs_v4_signed_url_redaction(self):
        """Verify that GCS signed URLs with query parameters have signature removed."""
        raw_signed_url = (
            "https://storage.googleapis.com/quakemap-media-data/steer/test_page1.pdf"
            "?X-Goog-Algorithm=GOOG4-RSA-SHA256"
            "&X-Goog-Credential=service-account%40project.iam.gserviceaccount.com"
            "&X-Goog-Date=20261107T214000Z"
            "&X-Goog-Expires=3600"
            "&X-Goog-SignedHeaders=host"
            "&X-Goog-Signature=abcdef0123456789fedcba9876543210deadbeef"
        )
        sanitized = redact_sensitive_strings(raw_signed_url)

        self.assertNotIn("X-Goog-Signature", sanitized)
        self.assertNotIn("abcdef0123456789fedcba9876543210deadbeef", sanitized)
        self.assertIn("https://storage.googleapis.com/quakemap-media-data/steer/test_page1.pdf", sanitized)
        self.assertIn("[REDACTED_SIGNATURE]", sanitized)

    def test_bearer_token_redaction(self):
        """Verify that OAuth / Bearer tokens are redacted."""
        text = "Authorization: Bearer ya29.a0AfH6SMCxExampleToken987654321"
        sanitized = redact_sensitive_strings(text)

        self.assertNotIn("ya29.a0AfH6SMCxExampleToken987654321", sanitized)
        self.assertIn("Bearer [REDACTED_TOKEN]", sanitized)

    def test_api_key_query_param_redaction(self):
        """Verify that API keys in URLs or strings are redacted."""
        url = "https://generativelanguage.googleapis.com/v1beta/models?key=AIzaSyD-FakeKey123456789"
        sanitized = redact_sensitive_strings(url)

        self.assertNotIn("AIzaSyD-FakeKey123456789", sanitized)
        self.assertIn("key=[REDACTED]", sanitized)

    def test_sanitize_payload_recursive_dictionary(self):
        """Verify that nested dictionaries and lists are thoroughly sanitized."""
        payload = {
            "blob_name": "steer/test_page1.pdf",
            "signed_url": "https://storage.googleapis.com/my-bucket/test.pdf?X-Goog-Signature=abc123secret",
            "api_key": "AIzaSyD-SecretKey",
            "token": "secret_session_token_xyz",
            "metadata": [
                {
                    "direct_url": "https://storage.googleapis.com/my-bucket/page.pdf?GoogleAccessId=sa@proj&Signature=xyz789",
                    "safe_field": "Sagaing city",
                }
            ],
            "nested": {
                "deep_key": "another_token_123",
            },
        }

        scrubbed = sanitize_payload(payload)

        # Sensitive keys should be replaced with [REDACTED]
        self.assertEqual(scrubbed["api_key"], "[REDACTED]")
        self.assertEqual(scrubbed["token"], "[REDACTED]")

        # Signed URL signatures should be redacted
        self.assertNotIn("abc123secret", scrubbed["signed_url"])
        self.assertIn("[REDACTED_SIGNATURE]", scrubbed["signed_url"])

        # Nested list item URL
        nested_url = scrubbed["metadata"][0]["direct_url"]
        self.assertNotIn("xyz789", nested_url)
        self.assertIn("[REDACTED_SIGNATURE]", nested_url)

        # Safe field remains intact
        self.assertEqual(scrubbed["metadata"][0]["safe_field"], "Sagaing city")

    def test_summarize_state_scrubs_sensitive_fields(self):
        """Verify that state summary logging strips large values and scrubs secrets."""
        state = {
            "signed_url": "https://storage.googleapis.com/my-bucket/test.pdf?Signature=secret",
            "prompt": "Evaluate this earthquake report " * 50,  # long string
            "mmi_value": 10.0,
        }
        summary = summarize_state(state)

        self.assertNotIn("secret", str(summary))
        self.assertIn("[REDACTED_SIGNATURE]", str(summary["signed_url"]))
        self.assertEqual(summary["mmi_value"], 10.0)

    def test_human_review_queue_disk_persistence_is_redacted(self):
        """Verify that persistent JSON records saved by HumanReviewQueue never contain raw secrets."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_review_queue.json"
            queue = HumanReviewQueue(persistence_file=db_path)

            sensitive_state = {
                "file_name": "test_page1.pdf",
                "signed_url": "https://storage.googleapis.com/bucket/test.pdf?X-Goog-Signature=forbidden_secret_signature",
                "api_key": "AIzaSySecretApiKey",
                "mmi": 10.0,
            }

            queue.check_and_enqueue("item_01", sensitive_state, force=True)

            # Inspect raw file on disk
            self.assertTrue(db_path.exists())
            raw_disk_text = db_path.read_text(encoding="utf-8")

            self.assertNotIn("forbidden_secret_signature", raw_disk_text)
            self.assertNotIn("AIzaSySecretApiKey", raw_disk_text)
            self.assertIn("[REDACTED_SIGNATURE]", raw_disk_text)
            self.assertIn("[REDACTED]", raw_disk_text)

    def test_logger_terminal_traces_and_events_redaction(self):
        """Verify that StructuredAgentLogger redacts signed URLs from events and node traces."""
        logger = StructuredAgentLogger(name="test_tracer", console_output=False)
        raw_url = "https://storage.googleapis.com/quakemap-media-data/file.pdf?X-Goog-Signature=topsecret123"

        # 1. Node enter
        enter_event = logger.log_node_enter("test_node", {"signed_url": raw_url, "doc": "test"})
        self.assertNotIn("topsecret123", str(enter_event.to_dict()))
        self.assertIn("[REDACTED_SIGNATURE]", str(enter_event.to_dict()["inputs"]["signed_url"]))

        # 2. Node exit
        exit_event = logger.log_node_exit("test_node", {"result_url": raw_url}, duration_ms=10.0)
        self.assertNotIn("topsecret123", str(exit_event.to_dict()))
        self.assertIn("[REDACTED_SIGNATURE]", str(exit_event.to_dict()["outputs"]["result_url"]))

    def test_logger_error_message_redaction(self):
        """Verify that exception messages containing signed URLs or secrets are scrubbed."""
        logger = StructuredAgentLogger(name="test_tracer", console_output=False)
        err = RuntimeError("Connection timeout to https://storage.googleapis.com/quakemap-media-data/file.pdf?X-Goog-Signature=secret_leak")

        err_event = logger.log_error("failing_node", err)
        clean_msg = err_event.metadata["error_message"]

        self.assertNotIn("secret_leak", clean_msg)
        self.assertIn("[REDACTED_SIGNATURE]", clean_msg)

    def test_crag_display_sanitization(self):
        """Verify that Clara's CRAG _sanitize_for_display helper correctly strips signatures."""
        import sys
        server_dir = Path(__file__).parents[1] / "server"
        if str(server_dir) not in sys.path:
            sys.path.insert(0, str(server_dir))

        from services.crag import _sanitize_for_display

        sample_state = {
            "signed_url": "https://storage.googleapis.com/quakemap-media-data/test.pdf?GoogleAccessId=sa@proj&Signature=supersecret456",
            "blob_name": "test.pdf",
            "mmi": 10.0,
        }

        sanitized = _sanitize_for_display(sample_state)
        self.assertNotIn("supersecret456", str(sanitized))
        self.assertIn("[REDACTED_SIGNATURE]", sanitized["signed_url"])
        self.assertEqual(sanitized["blob_name"], "test.pdf")
        self.assertEqual(sanitized["mmi"], 10.0)


if __name__ == "__main__":
    unittest.main()
