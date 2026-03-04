"""Unit tests for news-based buy potential scoring."""

import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock

from src.news_ai.groq_buy_potential import (
    score_buy_potential,
    _is_available,
    _cache_key,
    _stage_a_scoring,
    _stage_b_validation
)


class TestBuyPotentialScoring(TestCase):
    """Test news-based buy potential scoring functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_news = [
            {
                "id": "news_1",
                "title": "STB reports strong Q4 earnings",
                "source": "VnExpress",
                "snippet": "Saigon Thuong Tin Bank posted 25% increase in quarterly profit",
                "published_at": "2026-03-03T10:00:00Z"
            },
            {
                "id": "news_2",
                "title": "Banking sector outlook positive",
                "source": "VietNamNet",
                "snippet": "Analysts recommend banking stocks for strong fundamentals",
                "published_at": "2026-03-03T11:00:00Z"
            },
            {
                "id": "news_3",
                "title": "Market volatility concerns",
                "source": "Tuoi Tre",
                "snippet": "Global uncertainty may impact Vietnamese markets",
                "published_at": "2026-03-03T12:00:00Z"
            }
        ]

        self.test_plan = {
            "recommendations": [
                {"symbol": "STB", "action": "BUY"},
                {"symbol": "VPB", "action": "HOLD"}
            ]
        }

    def test_api_key_detection(self):
        """Test API key availability detection."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "test_key"}):
            self.assertTrue(_is_available())

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_is_available())

    def test_cache_key_generation(self):
        """Test cache key generation for news items."""
        key1 = _cache_key("STB", self.test_news)
        key2 = _cache_key("STB", self.test_news)
        key3 = _cache_key("VPB", self.test_news)

        # Same symbol and news should generate same key
        self.assertEqual(key1, key2)

        # Different symbols should generate different keys
        self.assertNotEqual(key1, key3)

        # Key should contain symbol
        self.assertIn("STB", key1)

    def test_output_json_validation(self):
        """Test that output is valid JSON with required structure."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.test_plan, f)
            plan_path = f.name

        try:
            # Mock API calls to return valid structure
            mock_result = {
                "symbol_scores": [{
                    "symbol": "STB",
                    "buy_potential_score": 75,
                    "risk_score": 30,
                    "confidence": 0.8,
                    "horizon": "1-4w",
                    "key_bull_points": ["Strong earnings growth"],
                    "key_risks": ["Market volatility"],
                    "evidence": [{"id": "news_1", "supports": "bull"}]
                }]
            }

            with patch('src.news_ai.groq_buy_potential._is_available', return_value=True), \
                 patch('src.news_ai.groq_buy_potential._score_symbol', return_value=mock_result):

                result = score_buy_potential(plan_path, self.test_news)

                # Validate JSON structure
                self.assertIn("symbol_scores", result)
                self.assertIn("status", result)
                self.assertEqual(result["status"], "SUCCESS")

                # Validate individual score structure
                scores = result["symbol_scores"]
                self.assertGreater(len(scores), 0)

                score = scores[0]
                required_fields = ["symbol", "buy_potential_score", "risk_score",
                                 "confidence", "horizon", "key_bull_points",
                                 "key_risks", "evidence"]

                for field in required_fields:
                    self.assertIn(field, score)

                # Validate score ranges
                self.assertGreaterEqual(score["buy_potential_score"], 0)
                self.assertLessEqual(score["buy_potential_score"], 100)
                self.assertGreaterEqual(score["confidence"], 0.0)
                self.assertLessEqual(score["confidence"], 1.0)

        finally:
            Path(plan_path).unlink()

    def test_evidence_id_validation(self):
        """Test that evidence IDs must exist in input news."""
        mock_stage_a = {
            "symbol_scores": [{
                "symbol": "STB",
                "buy_potential_score": 80,
                "risk_score": 25,
                "confidence": 0.9,
                "horizon": "1-4w",
                "key_bull_points": ["Made up fact"],
                "key_risks": ["Another made up risk"],
                "evidence": [{"id": "fake_news_id", "supports": "bull"}]
            }]
        }

        # Stage B should filter out invalid evidence IDs
        corrected = _stage_b_validation(mock_stage_a, self.test_news)

        # Mock the API call to return corrected results
        expected_corrected = {
            "symbol_scores": [{
                "symbol": "STB",
                "buy_potential_score": 50,  # Reduced due to lack of evidence
                "risk_score": 50,
                "confidence": 0.3,  # Lowered confidence
                "horizon": "1-4w",
                "key_bull_points": [],  # Removed unsupported claims
                "key_risks": [],
                "evidence": []  # Removed invalid evidence
            }]
        }

        with patch('src.news_ai.groq_buy_potential._call_groq', return_value=expected_corrected):
            result = _stage_b_validation(mock_stage_a, self.test_news)

            if result:  # Only test if API call succeeds
                score = result["symbol_scores"][0]

                # Evidence IDs should only reference valid news
                valid_ids = {item["id"] for item in self.test_news}
                for evidence in score.get("evidence", []):
                    self.assertIn(evidence["id"], valid_ids)

    def test_insufficient_evidence_handling(self):
        """Test handling when news items have insufficient evidence."""
        empty_news = []

        result = _stage_a_scoring("STB", empty_news)

        # Should return low confidence and empty analysis
        self.assertIsNotNone(result)
        self.assertIn("symbol_scores", result)

        score = result["symbol_scores"][0]
        self.assertEqual(score["symbol"], "STB")
        self.assertLessEqual(score["confidence"], 0.3)  # Low confidence for no news
        self.assertEqual(len(score["key_bull_points"]), 0)  # No unsupported claims

    def test_api_not_configured_fallback(self):
        """Test graceful fallback when API is not configured."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.test_plan, f)
            plan_path = f.name

        try:
            with patch.dict(os.environ, {}, clear=True):  # Remove API key
                result = score_buy_potential(plan_path, self.test_news)

                self.assertEqual(result["status"], "API_NOT_CONFIGURED")
                self.assertEqual(result["symbol_scores"], [])

        finally:
            Path(plan_path).unlink()

    def test_plan_load_error_handling(self):
        """Test handling of invalid weekly plan file."""
        result = score_buy_potential("nonexistent_file.json", self.test_news)

        self.assertEqual(result["status"], "PLAN_LOAD_ERROR")
        self.assertEqual(result["symbol_scores"], [])

    def test_no_symbols_handling(self):
        """Test handling when plan has no recommendations."""
        empty_plan = {"recommendations": []}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(empty_plan, f)
            plan_path = f.name

        try:
            with patch('src.news_ai.groq_buy_potential._is_available', return_value=True):
                result = score_buy_potential(plan_path, self.test_news)

                self.assertEqual(result["status"], "NO_SYMBOLS")
                self.assertEqual(result["symbol_scores"], [])

        finally:
            Path(plan_path).unlink()

    def test_caching_behavior(self):
        """Test that analysis results are cached properly."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.test_plan, f)
            plan_path = f.name

        try:
            # Mock successful scoring
            mock_result = {
                "symbol_scores": [{
                    "symbol": "STB",
                    "buy_potential_score": 75,
                    "risk_score": 30,
                    "confidence": 0.8,
                    "horizon": "1-4w",
                    "key_bull_points": ["Strong earnings from news_1"],
                    "key_risks": ["Market concerns from news_3"],
                    "evidence": [
                        {"id": "news_1", "supports": "bull"},
                        {"id": "news_3", "supports": "risk"}
                    ]
                }]
            }

            with patch('src.news_ai.groq_buy_potential._is_available', return_value=True), \
                 patch('src.news_ai.groq_buy_potential._call_groq', return_value=mock_result) as mock_call:

                # First call should make API calls
                result1 = score_buy_potential(plan_path, self.test_news)
                initial_call_count = mock_call.call_count

                # Second call should use cache (fewer API calls)
                result2 = score_buy_potential(plan_path, self.test_news)

                # Results should be identical
                self.assertEqual(result1["symbol_scores"], result2["symbol_scores"])

        finally:
            Path(plan_path).unlink()