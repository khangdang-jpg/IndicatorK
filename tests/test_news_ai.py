"""Unit tests for News AI module using Groq."""

import json
import os
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from src.news_ai.groq_client import (
    extract_news_scores,
    compose_weekly_digest,
    get_api_key,
    is_available,
    NewsScore,
    NewsAnalysis,
    _hash_news_items,
    _load_cache,
    _save_cache,
)


class TestNewsAI(unittest.TestCase):
    """Test cases for News AI functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.sample_news_items = [
            {
                "symbol": "VHM",
                "title": "Vinhomes reports strong Q4 results",
                "summary": "Real estate developer shows 15% revenue growth",
                "source": "VN Express"
            },
            {
                "symbol": "VIC",
                "title": "Vingroup expands retail operations",
                "summary": "New shopping centers planned for 2026",
                "source": "Cafef"
            }
        ]

        self.sample_plan = {
            "recommendations": [
                {"symbol": "VHM", "action": "BUY"},
                {"symbol": "VIC", "action": "HOLD"}
            ]
        }

    def test_api_key_detection(self):
        """Test API key detection from environment."""
        # Test with no API key
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_api_key())
            self.assertFalse(is_available())

        # Test with API key present
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key-123"}):
            self.assertEqual(get_api_key(), "test-key-123")
            self.assertTrue(is_available())

    def test_news_hash_generation(self):
        """Test that news items generate consistent hashes."""
        hash1 = _hash_news_items(self.sample_news_items)
        hash2 = _hash_news_items(self.sample_news_items)

        # Same input should produce same hash
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 16)  # Should be 16 chars

        # Different input should produce different hash
        modified_news = self.sample_news_items.copy()
        modified_news[0]["title"] = "Different title"
        hash3 = _hash_news_items(modified_news)
        self.assertNotEqual(hash1, hash3)

    def test_extract_news_scores_no_api_key(self):
        """Test news extraction behavior when API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            result = extract_news_scores(self.sample_news_items)

        # Should return empty analysis
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("generated", False))
        self.assertEqual(result.get("scores", {}), {})
        self.assertEqual(result.get("overall_sentiment", ""), "neutral")

    def test_extract_news_scores_empty_input(self):
        """Test news extraction with empty news items."""
        result = extract_news_scores([])

        # Should return neutral empty analysis
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("generated", False))
        self.assertEqual(result.get("scores", {}), {})
        self.assertEqual(result.get("overall_sentiment", ""), "neutral")

    @patch('src.news_ai.groq_client._call_groq_with_retry')
    def test_extract_news_scores_success(self, mock_call_groq):
        """Test successful news extraction."""
        # Mock successful API response
        mock_response = {
            "scores": {
                "VHM": [{
                    "symbol": "VHM",
                    "sentiment": "bullish",
                    "impact": 0.7,
                    "confidence": 0.8,
                    "summary": "Strong earnings drive positive sentiment",
                    "source": "VN Express"
                }],
                "VIC": [{
                    "symbol": "VIC",
                    "sentiment": "neutral",
                    "impact": 0.4,
                    "confidence": 0.6,
                    "summary": "Expansion plans show mixed signals",
                    "source": "Cafef"
                }]
            },
            "overall_sentiment": "bullish"
        }
        mock_call_groq.return_value = mock_response

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = extract_news_scores(self.sample_news_items)

        # Verify result structure
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("generated", False))
        self.assertEqual(result.get("overall_sentiment"), "bullish")

        scores = result.get("scores", {})
        self.assertIn("VHM", scores)
        self.assertIn("VIC", scores)

    @patch('src.news_ai.groq_client._call_groq_with_retry')
    def test_extract_news_scores_api_failure(self, mock_call_groq):
        """Test news extraction behavior when API call fails."""
        mock_call_groq.return_value = None

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = extract_news_scores(self.sample_news_items)

        # Should return empty analysis on failure
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("generated", False))
        self.assertEqual(result.get("scores", {}), {})

    def test_compose_weekly_digest_no_api_key(self):
        """Test digest composition behavior when API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            result = compose_weekly_digest(self.sample_plan, {})

        # Should return fallback message
        self.assertIsInstance(result, str)
        self.assertIn("unavailable", result.lower())
        self.assertIn("api key", result.lower())

    def test_compose_weekly_digest_no_scores(self):
        """Test digest composition with no news scores."""
        news_scores = {"generated": False, "scores": {}}

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = compose_weekly_digest(self.sample_plan, news_scores)

        # Should return fallback message
        self.assertIsInstance(result, str)
        self.assertIn("unavailable", result.lower())
        self.assertIn("no news", result.lower())

    @patch('src.news_ai.groq_client._call_groq_with_retry')
    def test_compose_weekly_digest_success(self, mock_call_groq):
        """Test successful digest composition."""
        # Mock successful API response
        mock_response = {
            "content": "This week shows strong momentum in Vietnamese equities with positive sentiment from earnings results..."
        }
        mock_call_groq.return_value = mock_response

        news_scores = {
            "generated": True,
            "overall_sentiment": "bullish",
            "scores": {
                "VHM": [{
                    "sentiment": "bullish",
                    "impact": 0.7,
                    "confidence": 0.8,
                    "summary": "Strong earnings"
                }]
            }
        }

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = compose_weekly_digest(self.sample_plan, news_scores)

        # Should return composed digest
        self.assertIsInstance(result, str)
        self.assertIn("strong momentum", result.lower())

    @patch('src.news_ai.groq_client._call_groq_with_retry')
    def test_compose_weekly_digest_api_failure(self, mock_call_groq):
        """Test digest composition behavior when API call fails."""
        mock_call_groq.return_value = None

        news_scores = {
            "generated": True,
            "overall_sentiment": "bullish",
            "scores": {"VHM": [{
                "sentiment": "bullish",
                "impact": 0.7,
                "confidence": 0.8,
                "summary": "Test summary"
            }]}
        }

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = compose_weekly_digest(self.sample_plan, news_scores)

        # Should return fallback message
        self.assertIsInstance(result, str)
        self.assertIn("unavailable", result.lower())
        self.assertIn("api issues", result.lower())

    def test_cache_operations(self):
        """Test cache loading and saving operations."""
        # Test cache with non-existent file
        cache = _load_cache()
        self.assertIsInstance(cache, dict)

        # Test cache saving and loading
        test_cache = {
            "test_hash": {
                "scores": {"VHM": [{"sentiment": "bullish"}]},
                "generated": True
            }
        }

        # Mock Path operations to avoid actual file I/O in tests
        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', unittest.mock.mock_open(read_data=json.dumps(test_cache))):
                loaded_cache = _load_cache()
                self.assertEqual(loaded_cache, test_cache)

        # Test save cache
        with patch('pathlib.Path.mkdir'):
            with patch('builtins.open', unittest.mock.mock_open()) as mock_file:
                _save_cache(test_cache)
                mock_file.assert_called_once()

    @patch('src.news_ai.groq_client._load_cache')
    @patch('src.news_ai.groq_client._save_cache')
    @patch('src.news_ai.groq_client._call_groq_with_retry')
    def test_caching_behavior(self, mock_call_groq, mock_save_cache, mock_load_cache):
        """Test that caching works correctly."""
        # Mock cache hit
        cached_result = {
            "scores": {"VHM": [{"sentiment": "bullish"}]},
            "generated": True,
            "cache_hit": True
        }
        news_hash = _hash_news_items(self.sample_news_items)
        mock_load_cache.return_value = {news_hash: cached_result}

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = extract_news_scores(self.sample_news_items)

        # Should return cached result without API call
        self.assertTrue(result.get("cache_hit", False))
        mock_call_groq.assert_not_called()

        # Test cache miss - should call API and save to cache
        # Reset mocks first
        mock_call_groq.reset_mock()
        mock_save_cache.reset_mock()
        mock_load_cache.reset_mock()

        mock_load_cache.return_value = {}  # Empty cache
        api_result = {
            "scores": {"VIC": [{"sentiment": "neutral"}]},
            "overall_sentiment": "neutral"
        }
        mock_call_groq.return_value = api_result

        result = extract_news_scores(self.sample_news_items)

        # Should have called API and saved to cache
        mock_call_groq.assert_called_once()
        mock_save_cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()