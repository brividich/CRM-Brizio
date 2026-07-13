"""Tests for AI Configuration Copilot"""

import json
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

# Disable real API calls in tests
import os
os.environ.setdefault("NVIDIA_NIM_API_KEY", "")
os.environ.setdefault("NVIDIA_API_KEY", "")

from security.api_ai import (
    AIConfigurationCopilotApiView,
    AIConfigurationContextPreviewApiView,
)
from security.ai.services.configuration_copilot import (
    build_configuration_context,
    build_configuration_copilot_prompt,
    context_quality_score,
    parse_ai_response,
    validate_task,
    validate_user_prompt,
)
from security.ai.providers.base import (
    AIProviderConfigurationError,
    AIProviderResponseError,
    AIProviderUnavailableError,
    AiResponse,
)
from security.models import (
    SecurityAiInteractionLog,
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityMailboxSource,
)


class TestConfigurationCopilotService(TestCase):
    """Test configuration copilot service"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass", is_staff=True)

    def test_build_configuration_context_includes_sources(self):
        """Context should include sources summary"""
        SecurityMailboxSource.objects.create(
            name="Test Source",
            code="test-source",
            enabled=True,
            source_type="email",
        )

        context = build_configuration_context()

        self.assertTrue(context.get("context_available"))
        self.assertIn("sources", context)
        self.assertGreater(len(context["sources"]), 0)
        self.assertEqual(context["sources"][0]["code"], "test-source")

    def test_build_configuration_context_includes_rules(self):
        """Context should include rules summary"""
        SecurityAlertRuleConfig.objects.create(
            name="Test Rule",
            code="test-rule",
            enabled=True,
            source_type="test",
            severity="high",
            metric_name="test_metric",
            condition_operator="gte",
            threshold_value="10",
        )

        context = build_configuration_context()

        self.assertTrue(context.get("context_available"))
        self.assertIn("rules", context)
        self.assertGreater(len(context["rules"]), 0)
        self.assertEqual(context["rules"][0]["code"], "test-rule")

    def test_build_configuration_context_includes_suppressions(self):
        """Context should include suppressions summary"""
        SecurityAlertSuppressionRule.objects.create(
            name="Test Suppression",
            is_active=True,
            event_type="test_event",
        )

        context = build_configuration_context()

        self.assertTrue(context.get("context_available"))
        self.assertIn("suppressions", context)
        self.assertGreater(len(context["suppressions"]), 0)

    def test_build_configuration_context_includes_capabilities(self):
        """Context should include system capabilities"""
        context = build_configuration_context()

        self.assertTrue(context.get("context_available"))
        self.assertIn("capabilities", context)
        self.assertIn("supported_source_types", context["capabilities"])
        self.assertIn("supported_vendors", context["capabilities"])
        self.assertIn("supported_severities", context["capabilities"])

    def test_build_configuration_context_includes_warnings(self):
        """Context should include warnings for missing configuration"""
        context = build_configuration_context()

        self.assertTrue(context.get("context_available"))
        self.assertIn("warnings", context)
        self.assertIsInstance(context["warnings"], list)

    def test_build_configuration_context_includes_limits(self):
        """Context should include truncation limits"""
        context = build_configuration_context()

        self.assertTrue(context.get("context_available"))
        self.assertIn("limits", context)
        self.assertIn("max_chars", context["limits"])
        self.assertIn("truncated", context["limits"])

    def test_build_configuration_copilot_prompt_includes_system_prompt(self):
        """Prompt should include system prompt"""
        messages = build_configuration_copilot_prompt(
            task="suggest_source",
            user_prompt="Test prompt",
            context={},
        )

        self.assertGreater(len(messages), 0)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Configuration Copilot", messages[0]["content"])

    def test_build_configuration_copilot_prompt_includes_context(self):
        """Prompt should include configuration context"""
        test_context = {
            "sources": [{"code": "test", "name": "Test"}],
            "rules": [],
        }

        messages = build_configuration_copilot_prompt(
            task="suggest_source",
            user_prompt="Test prompt",
            context=test_context,
        )

        context_message = [msg for msg in messages if "Configuration Context:" in msg.get("content", "")]
        self.assertEqual(len(context_message), 1)

    def test_build_configuration_copilot_prompt_includes_draft(self):
        """Prompt should include existing draft when provided"""
        test_draft = {"name": "Test", "enabled": True}

        messages = build_configuration_copilot_prompt(
            task="improve_rule",
            user_prompt="Test prompt",
            context={},
            draft=test_draft,
        )

        user_message = messages[-1]
        self.assertIn("Existing Draft:", user_message["content"])

    def test_build_configuration_copilot_prompt_includes_sample(self):
        """Prompt should include sample data when provided"""
        test_sample = "Sample data for testing"

        messages = build_configuration_copilot_prompt(
            task="suggest_rule",
            user_prompt="Test prompt",
            context={},
            sample=test_sample,
        )

        user_message = messages[-1]
        self.assertIn("Sample Data:", user_message["content"])

    def test_build_configuration_copilot_prompt_includes_scope(self):
        """Prompt should include scope when provided"""
        test_scope = {"source_code": "test-source"}

        messages = build_configuration_copilot_prompt(
            task="explain_rule",
            user_prompt="Test prompt",
            context={},
            scope=test_scope,
        )

        user_message = messages[-1]
        self.assertIn("Scope:", user_message["content"])

    def test_parse_ai_response_extracts_json_from_code_block(self):
        """Should extract JSON from markdown code block"""
        response_content = '```json\n{"test": "value"}\n```'
        result = parse_ai_response(response_content)

        self.assertEqual(result, {"test": "value"})

    def test_parse_ai_response_handles_plain_json(self):
        """Should handle plain JSON without code block"""
        response_content = '{"test": "value"}'
        result = parse_ai_response(response_content)

        self.assertEqual(result, {"test": "value"})

    def test_parse_ai_response_removes_control_characters(self):
        """Should remove control characters from JSON"""
        response_content = '{"test": "value\x00\x1f"}'
        result = parse_ai_response(response_content)

        self.assertEqual(result, {"test": "value"})

    def test_parse_ai_response_raises_on_invalid_json(self):
        """Should raise ValueError on invalid JSON"""
        response_content = "not valid json"

        with self.assertRaises(ValueError):
            parse_ai_response(response_content)

    def test_validate_task_accepts_allowed_tasks(self):
        """Should accept all allowed tasks"""
        allowed_tasks = [
            "suggest_source",
            "suggest_rule",
            "improve_rule",
            "explain_rule",
            "suggest_suppression",
            "review_configuration",
            "test_plan",
        ]

        for task in allowed_tasks:
            self.assertTrue(validate_task(task), f"Task {task} should be valid")

    def test_validate_task_rejects_invalid_tasks(self):
        """Should reject invalid tasks"""
        invalid_tasks = ["invalid", "create_source", "delete_rule", ""]

        for task in invalid_tasks:
            self.assertFalse(validate_task(task), f"Task {task} should be invalid")

    def test_validate_user_prompt_accepts_valid_prompt(self):
        """Should accept valid user prompts"""
        self.assertTrue(validate_user_prompt("Valid prompt"))
        self.assertTrue(validate_user_prompt("Another valid prompt with more text"))

    def test_validate_user_prompt_rejects_empty_prompt(self):
        """Should reject empty prompts"""
        self.assertFalse(validate_user_prompt(""))
        self.assertFalse(validate_user_prompt("   "))

    def test_validate_user_prompt_rejects_too_long_prompt(self):
        """Should reject prompts that are too long"""
        long_prompt = "a" * 2001
        self.assertFalse(validate_user_prompt(long_prompt))

    def test_validate_user_prompt_rejects_non_string_prompt(self):
        """Should reject non-string prompts"""
        self.assertFalse(validate_user_prompt(123))
        self.assertFalse(validate_user_prompt(None))
        self.assertFalse(validate_user_prompt({}))

    def test_context_quality_score_empty_context(self):
        """Should return empty score for unavailable context"""
        context = {"context_available": False}
        quality = context_quality_score(context)

        self.assertEqual(quality["score"], 0)
        self.assertEqual(quality["level"], "empty")

    def test_context_quality_score_calculates_score(self):
        """Should calculate quality score based on activity"""
        context = {
            "context_available": True,
            "recent_activity": {
                "sources_count": 5,
                "enabled_sources_count": 3,
                "rules_count": 10,
                "active_rules_count": 8,
                "parsers_count": 5,
                "notifications_count": 4,
                "suppressions_count": 2,
            },
        }

        quality = context_quality_score(context)

        self.assertGreater(quality["score"], 0)
        self.assertLessEqual(quality["score"], 100)
        self.assertIn(quality["level"], ["empty", "poor", "partial", "good", "complete"])

    def test_context_quality_score_complete_level(self):
        """Should return complete level for high scores"""
        context = {
            "context_available": True,
            "recent_activity": {
                "sources_count": 10,
                "enabled_sources_count": 5,
                "rules_count": 20,
                "active_rules_count": 15,
                "parsers_count": 10,
                "notifications_count": 4,
                "suppressions_count": 5,
            },
        }

        quality = context_quality_score(context)

        self.assertEqual(quality["level"], "complete")

    def test_context_quality_score_poor_level(self):
        """Should return poor level for low scores"""
        context = {
            "context_available": True,
            "recent_activity": {
                "sources_count": 1,
                "enabled_sources_count": 0,
                "rules_count": 0,
                "active_rules_count": 0,
                "parsers_count": 0,
                "notifications_count": 0,
                "suppressions_count": 0,
            },
        }

        quality = context_quality_score(context)

        self.assertEqual(quality["level"], "poor")


class TestAIConfigurationCopilotApiView(TestCase):
    """Test AI Configuration Copilot API endpoint"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AIConfigurationCopilotApiView.as_view()
        self.user = User.objects.create_user(username="testuser", password="testpass", is_staff=True)

    def _make_authenticated_request(self, data):
        """Helper to make authenticated request"""
        request = self.factory.post("/api/security/ai/configuration-copilot/", data, format="json")
        force_authenticate(request, user=self.user)
        return self.view(request)

    def test_invalid_task_returns_400(self):
        """Invalid task should return 400"""
        response = self._make_authenticated_request({
            "task": "invalid_task",
            "user_prompt": "Test prompt",
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_task")

    def test_empty_user_prompt_returns_400(self):
        """Empty user_prompt should return 400"""
        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "",
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_request")

    def test_whitespace_only_user_prompt_returns_400(self):
        """Whitespace-only user_prompt should return 400"""
        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "   ",
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_request")

    @patch("security.api_ai.chat_completion")
    def test_provider_not_configured_returns_503(self, mock_chat):
        """Provider not configured should return 503"""
        mock_chat.side_effect = AIProviderConfigurationError("NVIDIA_NIM_API_KEY not configured")

        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Test prompt",
        })

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"], "AI service not configured")
        self.assertEqual(response.data["code"], "provider_not_configured")
        self.assertEqual(response.data["retryable"], False)

    @patch("security.api_ai.chat_completion")
    def test_provider_unavailable_returns_503(self, mock_chat):
        """Provider unavailable should return 503"""
        mock_chat.side_effect = AIProviderUnavailableError("provider detail")

        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Test prompt",
        })

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"], "AI service temporarily unavailable")
        self.assertEqual(response.data["code"], "provider_unavailable")
        self.assertEqual(response.data["retryable"], True)

    @patch("security.api_ai.chat_completion")
    def test_provider_response_error_returns_503(self, mock_chat):
        """Provider response error should return 503"""
        mock_chat.side_effect = AIProviderResponseError("invalid response")

        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Test prompt",
        })

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"], "AI service temporarily unavailable")
        self.assertEqual(response.data["code"], "provider_response_error")
        self.assertEqual(response.data["retryable"], True)

    @patch("security.api_ai.chat_completion")
    def test_successful_suggest_source(self, mock_chat):
        """Successful suggest_source should return structured response"""
        mock_chat.return_value = AiResponse(
            content='{"task": "suggest_source", "summary": "Test summary", "confidence": "high", "draft": {"name": "Test Source"}, "rationale": ["Test rationale"], "warnings": [], "missing_information": []}',
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )

        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Voglio monitorare le email WatchGuard",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["task"], "suggest_source")
        self.assertEqual(response.data["summary"], "Test summary")
        self.assertEqual(response.data["confidence"], "high")
        self.assertEqual(response.data["safe_to_apply"], False)
        self.assertEqual(response.data["requires_review"], True)

    @patch("security.api_ai.chat_completion")
    def test_successful_suggest_rule(self, mock_chat):
        """Successful suggest_rule should return structured response"""
        mock_chat.return_value = AiResponse(
            content='{"task": "suggest_rule", "summary": "Test rule", "confidence": "medium", "draft": {"code": "test-rule", "name": "Test Rule"}, "rationale": ["Test rationale"], "warnings": [], "missing_information": []}',
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )

        response = self._make_authenticated_request({
            "task": "suggest_rule",
            "user_prompt": "Genera una regola per Defender critical",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["task"], "suggest_rule")
        self.assertIn("draft", response.data)

    @patch("security.api_ai.chat_completion")
    def test_invalid_json_response_returns_503(self, mock_chat):
        """Invalid JSON response should return 503"""
        mock_chat.return_value = AiResponse(
            content="not valid json",
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )

        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Test prompt",
        })

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "provider_response_error")

    @patch("security.api_ai.chat_completion")
    def test_logs_successful_interaction(self, mock_chat):
        """Should log successful interaction"""
        mock_chat.return_value = AiResponse(
            content='{"task": "suggest_source", "summary": "Test", "confidence": "high", "draft": {}, "rationale": [], "warnings": [], "missing_information": []}',
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )

        self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Test prompt",
        })

        log = SecurityAiInteractionLog.objects.get()
        self.assertEqual(log.action, "configuration_copilot")
        self.assertEqual(log.status, "success")
        self.assertEqual(log.page, "configuration")
        self.assertEqual(log.object_type, "config")
        self.assertEqual(log.object_id, "suggest_source")

    @patch("security.api_ai.chat_completion")
    def test_logs_provider_error(self, mock_chat):
        """Should log provider error"""
        mock_chat.side_effect = AIProviderUnavailableError("provider detail")

        self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Test prompt",
        })

        log = SecurityAiInteractionLog.objects.get()
        self.assertEqual(log.action, "configuration_copilot")
        self.assertEqual(log.status, "provider_error")
        self.assertEqual(log.error_message, "AIProviderUnavailableError")

    @patch("security.api_ai.chat_completion")
    def test_includes_sample_in_request(self, mock_chat):
        """Should include sample data when provided"""
        mock_chat.return_value = AiResponse(
            content='{"task": "suggest_source", "summary": "Test", "confidence": "high", "draft": {}, "rationale": [], "warnings": [], "missing_information": []}',
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )

        response = self._make_authenticated_request({
            "task": "suggest_source",
            "user_prompt": "Test prompt",
            "sample": "Sample data",
        })

        self.assertEqual(response.status_code, 200)
        # Verify sample was included in the AI call
        call_args = mock_chat.call_args
        messages = call_args[1]["messages"]
        user_message = messages[-1]["content"]
        self.assertIn("Sample Data:", user_message)

    @patch("security.api_ai.chat_completion")
    def test_includes_draft_in_request(self, mock_chat):
        """Should include existing draft when provided"""
        mock_chat.return_value = AiResponse(
            content='{"task": "improve_rule", "summary": "Test", "confidence": "high", "draft": {}, "rationale": [], "warnings": [], "missing_information": []}',
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )

        response = self._make_authenticated_request({
            "task": "improve_rule",
            "user_prompt": "Test prompt",
            "draft": {"name": "Existing Rule"},
        })

        self.assertEqual(response.status_code, 200)
        # Verify draft was included in the AI call
        call_args = mock_chat.call_args
        messages = call_args[1]["messages"]
        user_message = messages[-1]["content"]
        self.assertIn("Existing Draft:", user_message)

    @patch("security.api_ai.chat_completion")
    def test_includes_scope_in_request(self, mock_chat):
        """Should include scope when provided"""
        mock_chat.return_value = AiResponse(
            content='{"task": "explain_rule", "summary": "Test", "confidence": "high", "draft": {}, "rationale": [], "warnings": [], "missing_information": []}',
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )

        response = self._make_authenticated_request({
            "task": "explain_rule",
            "user_prompt": "Test prompt",
            "scope": {"rule_code": "test-rule"},
        })

        self.assertEqual(response.status_code, 200)
        # Verify scope was included in the AI call
        call_args = mock_chat.call_args
        messages = call_args[1]["messages"]
        user_message = messages[-1]["content"]
        self.assertIn("Scope:", user_message)


class TestAIConfigurationContextPreviewApiView(TestCase):
    """Test AI Configuration Context Preview API endpoint"""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AIConfigurationContextPreviewApiView.as_view()
        self.user = User.objects.create_user(username="testuser", password="testpass", is_staff=True)

    def _make_authenticated_request(self):
        """Helper to make authenticated request"""
        request = self.factory.get("/api/security/ai/configuration-context-preview/")
        force_authenticate(request, user=self.user)
        return self.view(request)

    def test_returns_context_preview(self):
        """Should return context preview"""
        response = self._make_authenticated_request()

        self.assertEqual(response.status_code, 200)
        self.assertIn("context_available", response.data)
        self.assertIn("sources_count", response.data)
        self.assertIn("parsers_count", response.data)
        self.assertIn("rules_count", response.data)
        self.assertIn("suppressions_count", response.data)
        self.assertIn("notifications_count", response.data)
        self.assertIn("warnings", response.data)
        self.assertIn("quality", response.data)

    def test_includes_quality_score(self):
        """Should include quality score"""
        response = self._make_authenticated_request()

        self.assertIn("quality", response.data)
        self.assertIn("score", response.data["quality"])
        self.assertIn("level", response.data["quality"])
        self.assertIsInstance(response.data["quality"]["score"], int)
        self.assertIn(response.data["quality"]["level"], ["empty", "poor", "partial", "good", "complete"])

    def test_includes_counts(self):
        """Should include counts for each entity type"""
        SecurityMailboxSource.objects.create(
            name="Test Source",
            code="test-source",
            enabled=True,
            source_type="email",
        )
        SecurityAlertRuleConfig.objects.create(
            name="Test Rule",
            code="test-rule",
            enabled=True,
            source_type="test",
            severity="high",
        )

        response = self._make_authenticated_request()

        self.assertGreater(response.data["sources_count"], 0)
        self.assertGreater(response.data["rules_count"], 0)
