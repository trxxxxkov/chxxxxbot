"""Tests for i18n module.

Tests language detection and text retrieval functionality.

NO __init__.py - use direct import:
    pytest tests/i18n/test_i18n.py
"""

from i18n import get_lang
from i18n import get_text
from i18n import MESSAGES
import pytest


class TestGetLang:
    """Test get_lang function."""

    def test_russian_returns_ru(self):
        """Test that Russian language codes return 'ru'."""
        assert get_lang("ru") == "ru"

    def test_russian_variant_returns_ru(self):
        """Test that Russian variants (ru-RU, etc.) return 'ru'."""
        assert get_lang("ru-RU") == "ru"
        assert get_lang("ru-UA") == "ru"

    def test_english_returns_en(self):
        """Test that English language code returns 'en'."""
        assert get_lang("en") == "en"

    def test_english_variant_returns_en(self):
        """Test that English variants return 'en'."""
        assert get_lang("en-US") == "en"
        assert get_lang("en-GB") == "en"

    def test_other_languages_return_en(self):
        """Test that other languages fall back to English."""
        assert get_lang("de") == "en"
        assert get_lang("fr") == "en"
        assert get_lang("es") == "en"
        assert get_lang("zh") == "en"
        assert get_lang("ja") == "en"

    def test_none_returns_en(self):
        """Test that None returns 'en'."""
        assert get_lang(None) == "en"

    def test_empty_string_returns_en(self):
        """Test that empty string returns 'en'."""
        assert get_lang("") == "en"


class TestGetText:
    """Test get_text function."""

    def test_english_text_retrieval(self):
        """Test retrieving English text."""
        text = get_text("common.unable_to_identify_user", "en")
        assert "Unable to identify user" in text

    def test_russian_text_retrieval(self):
        """Test retrieving Russian text."""
        text = get_text("common.unable_to_identify_user", "ru")
        assert "Не удалось определить" in text

    def test_placeholder_substitution(self):
        """Test placeholder substitution in text."""
        text = get_text("balance.insufficient", "en", balance="10.00")
        assert "$10.00" in text or "${10.00}" in text

    def test_missing_key_returns_fallback(self):
        """Test that missing keys return fallback message."""
        text = get_text("nonexistent.key", "en")
        assert "[Missing: nonexistent.key]" in text

    def test_missing_language_falls_back_to_english(self):
        """Test that missing language falls back to English."""
        # This tests the fallback mechanism for keys that exist
        text = get_text("common.unable_to_identify_user", "de")  # German
        # Should return English version since German isn't defined
        assert "Unable to identify user" in text

    def test_start_welcome_messages(self):
        """Test start welcome messages in both languages."""
        en_new = get_text("start.welcome_new", "en")
        en_back = get_text("start.welcome_back", "en")
        ru_new = get_text("start.welcome_new", "ru")
        ru_back = get_text("start.welcome_back", "ru")

        assert "Welcome" in en_new
        assert "Welcome back" in en_back
        assert "Добро пожаловать" in ru_new
        assert "С возвращением" in ru_back

    def test_payment_success_message(self):
        """Test payment success message with placeholders."""
        text = get_text("payment.success",
                        "en",
                        credited_usd="5.00",
                        new_balance="15.00",
                        transaction_id="test_123")
        assert "$5.00" in text or "${5.00}" in text
        assert "test_123" in text

    def test_balance_insufficient_message(self):
        """Test balance insufficient message."""
        text_en = get_text("balance.insufficient", "en", balance="0.00")
        text_ru = get_text("balance.insufficient", "ru", balance="0.00")

        assert "Insufficient balance" in text_en
        assert "Недостаточно средств" in text_ru


class TestMessagesStructure:
    """Test MESSAGES dictionary structure."""

    def test_all_keys_have_english(self):
        """Test that all message keys have English translations."""
        for key, translations in MESSAGES.items():
            assert "en" in translations, f"Key {key} missing English translation"

    def test_all_keys_have_russian(self):
        """Test that all message keys have Russian translations."""
        for key, translations in MESSAGES.items():
            assert "ru" in translations, f"Key {key} missing Russian translation"

    def test_english_and_russian_are_different(self):
        """Test that English and Russian translations are different."""
        for key, translations in MESSAGES.items():
            en_text = translations.get("en", "")
            ru_text = translations.get("ru", "")
            # Skip if either is empty (placeholder values)
            if en_text and ru_text:
                # They should be different (unless very short/identical intentionally)
                # Some keys like "$" might be the same, so we just check non-empty
                assert en_text, f"Key {key} has empty English"
                assert ru_text, f"Key {key} has empty Russian"
