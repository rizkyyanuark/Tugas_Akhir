"""Tests interrupt-related helpers in chat_service."""

from yuxi.services.chat_service import (
    _normalize_interrupt_options,
    _normalize_interrupt_questions,
    _build_ask_user_question_payload,
    _coerce_interrupt_payload,
)
import sys
import os

sys.path.insert(0, os.getcwd())


class TestNormalizeInterruptOptions:
    """Tests for _normalize_interrupt_options."""

    def test_empty_input(self):
        assert _normalize_interrupt_options(None) == []
        assert _normalize_interrupt_options([]) == []

    def test_dict_options(self):
        raw = [
            {"label": "Option 1", "value": "option1"},
            {"label": "Option 2", "value": "option2"},
        ]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 2
        assert result[0] == {"label": "Option 1", "value": "option1"}
        assert result[1] == {"label": "Option 2", "value": "option2"}

    def test_string_options(self):
        raw = ["Option 1", "Option 2", "Option 3"]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 3
        assert result[0] == {"label": "Option 1", "value": "Option 1"}

    def test_mixed_options(self):
        raw = [{"label": "Option 1", "value": "option1"}, "Option 2"]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 2
        assert result[0] == {"label": "Option 1", "value": "option1"}
        assert result[1] == {"label": "Option 2", "value": "Option 2"}

    def test_invalid_options(self):
        raw = [{"label": "Label only"}, {}, "  "]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 1  # Only valid options should remain.
        assert result[0] == {"label": "Label only", "value": "Label only"}

    def test_value_only(self):
        raw = [{"value": "only_value"}]
        result = _normalize_interrupt_options(raw)
        assert len(result) == 1
        assert result[0] == {"label": "only_value", "value": "only_value"}


class TestBuildAskUserQuestionPayload:
    """Tests for _build_ask_user_question_payload."""

    def test_basic_questions(self):
        info = {
            "questions": [
                {
                    "question": "Please confirm whether to continue?",
                    "options": [
                        {"label": "Confirm", "value": "yes"},
                        {"label": "Cancel", "value": "no"},
                    ],
                }
            ],
        }
        result = _build_ask_user_question_payload(info, "thread-123")

        assert len(result["questions"]) == 1
        assert result["questions"][0]["question"] == "Please confirm whether to continue?"
        assert len(result["questions"][0]["options"]) == 2
        assert result["questions"][0]["options"][0] == {
            "label": "Confirm", "value": "yes"}
        assert result["questions"][0]["options"][1] == {
            "label": "Cancel", "value": "no"}
        assert result["source"] == "interrupt"
        assert result["thread_id"] == "thread-123"

    def test_questions_with_source(self):
        info = {
            "questions": [{"question": "Choose one option", "options": ["A", "B", "C"]}],
            "source": "ask_user_question",
        }
        result = _build_ask_user_question_payload(info, "thread-456")

        assert result["source"] == "ask_user_question"
        assert len(result["questions"][0]["options"]) == 3

    def test_multi_select(self):
        info = {
            "questions": [
                {
                    "question": "Select multiple",
                    "options": ["A", "B", "C"],
                    "multi_select": True,
                }
            ],
        }
        result = _build_ask_user_question_payload(info, "thread-789")

        assert result["questions"][0]["multi_select"] is True

    def test_disable_allow_other(self):
        info = {
            "questions": [{"question": "Must choose from options", "options": ["A", "B"], "allow_other": False}],
        }
        result = _build_ask_user_question_payload(info, "thread-000")

        assert result["questions"][0]["allow_other"] is False

    def test_with_operation(self):
        info = {
            "questions": [
                {
                    "question": "Do you want to execute this operation?",
                    "operation": "Delete file",
                    "options": [
                        {"label": "Approve", "value": "approve"},
                        {"label": "Reject", "value": "reject"},
                    ],
                }
            ],
        }
        result = _build_ask_user_question_payload(info, "thread-op")

        assert result["questions"][0]["operation"] == "Delete file"

    def test_default_question_when_questions_missing(self):
        info = {}
        result = _build_ask_user_question_payload(info, "thread-no-opt")

        assert len(result["questions"]) == 1
        assert isinstance(result["questions"][0]["question"], str)
        assert result["questions"][0]["question"].strip() != ""
        assert result["questions"][0]["options"] == []
        assert result["source"] == "interrupt"

    def test_legacy_single_question_payload(self):
        info = {
            "question": "Legacy protocol question",
            "question_id": "legacy-qid",
            "options": ["A", "B"],
            "multi_select": True,
            "allow_other": False,
            "operation": "Legacy operation",
        }
        result = _build_ask_user_question_payload(info, "thread-legacy")

        assert len(result["questions"]) == 1
        assert result["questions"][0]["question"] == "Legacy protocol question"
        assert result["questions"][0]["question_id"] == "legacy-qid"
        assert result["questions"][0]["options"] == [
            {"label": "A", "value": "A"},
            {"label": "B", "value": "B"},
        ]
        assert result["questions"][0]["multi_select"] is True
        assert result["questions"][0]["allow_other"] is False
        assert result["questions"][0]["operation"] == "Legacy operation"

    def test_question_id_generation(self):
        """Tests automatic question_id generation."""
        info = {"questions": [{"question": "Test?"}]}
        result = _build_ask_user_question_payload(info, "thread-id")

        assert result["questions"][0]["question_id"] != ""
        assert len(result["questions"][0]["question_id"]) > 0


class TestNormalizeInterruptQuestions:
    """Tests for _normalize_interrupt_questions."""

    def test_empty_input(self):
        assert _normalize_interrupt_questions(None) == []
        assert _normalize_interrupt_questions([]) == []

    def test_normalize_basic_question(self):
        raw = [{"question": "Q1", "options": ["A", "B"]}]
        result = _normalize_interrupt_questions(raw)

        assert len(result) == 1
        assert result[0]["question"] == "Q1"
        assert result[0]["options"][0] == {"label": "A", "value": "A"}
        assert result[0]["multi_select"] is False
        assert result[0]["allow_other"] is True

    def test_invalid_question_filtered(self):
        raw = [{"question": "  "}, "Q2", {"question": "Valid question"}]
        result = _normalize_interrupt_questions(raw)

        assert len(result) == 1
        assert result[0]["question"] == "Valid question"


class TestCoerceInterruptPayload:
    """Tests for _coerce_interrupt_payload."""

    def test_dict_input(self):
        info = {"question": "test?", "options": ["a", "b"]}
        result = _coerce_interrupt_payload(info)
        assert result == info

    def test_string_input(self):
        info = "just a string"
        result = _coerce_interrupt_payload(info)
        assert isinstance(result, dict)

    def test_none_input(self):
        result = _coerce_interrupt_payload(None)
        assert isinstance(result, dict)
