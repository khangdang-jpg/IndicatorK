"""Unit tests for Groq API integration."""

import json
import os
import unittest
from unittest.mock import Mock, patch, MagicMock

from src.ai.groq_analyzer import (
    analyze_weekly_plan,
    get_api_key,
    is_available,
    AIAnalysis,
    AIScore,
    _build_scoring_prompt,
    _call_groq,
)


class TestGroqIntegration(unittest.TestCase):
    """Test cases for Groq API integration."""

    def setUp(self):
        """Set up test fixtures."""
        self.sample_plan = {
            "recommendations": [
                {
                    "symbol": "VHM",
                    "action": "BUY",
                    "entry_type": "breakout",
                    "entry_price": 52500,
                    "stop_loss": 50000,
                    "take_profit": 58000,
                    "rationale_bullets": ["Strong weekly trend", "Good entry setup"]
                },
                {
                    "symbol": "VIC",
                    "action": "BUY",
                    "entry_type": "pullback",
                    "entry_price": 78500,
                    "stop_loss": 75000,
                    "take_profit": 85000,
                    "rationale_bullets": ["Pullback to support", "Risk/reward favorable"]
                }
            ]
        }

        self.sample_portfolio = "60% cash, 40% stocks (VHM 15%, VIC 25%)"

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

    def test_prompt_building(self):
        """Test that scoring prompt is built correctly."""
        prompt = _build_scoring_prompt(
            self.sample_plan["recommendations"],
            self.sample_portfolio,
            "2026-03-03T10:00:00Z"
        )

        # Check key components are present
        self.assertIn("Vietnamese stock analyst", prompt)
        self.assertIn("VHM", prompt)
        self.assertIn("VIC", prompt)
        self.assertIn("DATA AS OF: 2026-03-03T10:00:00Z", prompt)
        self.assertIn(self.sample_portfolio, prompt)
        self.assertIn("JSON", prompt)

    @patch('src.ai.groq_analyzer._call_groq')
    def test_analyze_weekly_plan_success(self, mock_call_groq):
        """Test successful analysis with valid response."""
        # Mock successful API response
        mock_response = {
            "scores": {
                "VHM": {
                    "score": 8,
                    "rationale": "Strong technical setup with good risk/reward",
                    "risk_note": ""
                },
                "VIC": {
                    "score": 7,
                    "rationale": "Good pullback opportunity",
                    "risk_note": "Monitor volume confirmation"
                }
            },
            "market_context": "Market showing weekly strength"
        }
        mock_call_groq.return_value = mock_response

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = analyze_weekly_plan(
                self.sample_plan,
                self.sample_portfolio,
                "2026-03-03T10:00:00Z"
            )

        # Verify result structure
        self.assertIsInstance(result, AIAnalysis)
        self.assertTrue(result.generated)
        self.assertEqual(result.market_context, "Market showing weekly strength")
        self.assertEqual(len(result.scores), 2)

        # Check individual scores
        vhm_score = result.scores["VHM"]
        self.assertIsInstance(vhm_score, AIScore)
        self.assertEqual(vhm_score.symbol, "VHM")
        self.assertEqual(vhm_score.score, 8)
        self.assertIn("Strong technical", vhm_score.rationale)

        vic_score = result.scores["VIC"]
        self.assertEqual(vic_score.score, 7)
        self.assertEqual(vic_score.risk_note, "Monitor volume confirmation")

    def test_analyze_weekly_plan_no_api_key(self):
        """Test analysis behavior when API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            result = analyze_weekly_plan(
                self.sample_plan,
                self.sample_portfolio
            )

        # Should return empty analysis
        self.assertIsInstance(result, AIAnalysis)
        self.assertFalse(result.generated)
        self.assertEqual(len(result.scores), 0)

    def test_analyze_weekly_plan_no_recommendations(self):
        """Test analysis behavior with empty recommendations."""
        empty_plan = {"recommendations": []}

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = analyze_weekly_plan(empty_plan, self.sample_portfolio)

        # Should return analysis with no recommendations message
        self.assertIsInstance(result, AIAnalysis)
        self.assertTrue(result.generated)
        self.assertEqual(result.market_context, "No recommendations to analyze.")
        self.assertEqual(len(result.scores), 0)

    @patch('src.ai.groq_analyzer._call_groq')
    def test_analyze_weekly_plan_api_failure(self, mock_call_groq):
        """Test analysis behavior when API call fails."""
        mock_call_groq.return_value = None

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = analyze_weekly_plan(
                self.sample_plan,
                self.sample_portfolio
            )

        # Should return empty analysis on failure
        self.assertIsInstance(result, AIAnalysis)
        self.assertFalse(result.generated)
        self.assertEqual(len(result.scores), 0)

    def test_score_validation(self):
        """Test that scores are properly validated and clamped."""
        mock_response = {
            "scores": {
                "VHM": {"score": 15, "rationale": "Test", "risk_note": ""},  # Too high
                "VIC": {"score": -5, "rationale": "Test", "risk_note": ""},  # Too low
                "FPT": {"score": 7.5, "rationale": "Test", "risk_note": ""}  # Float
            },
            "market_context": "Test context"
        }

        with patch('src.ai.groq_analyzer._call_groq', return_value=mock_response):
            with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
                result = analyze_weekly_plan(self.sample_plan, self.sample_portfolio)

        # Check score clamping
        self.assertEqual(result.scores["VHM"].score, 10)  # Clamped to max
        self.assertEqual(result.scores["VIC"].score, 1)   # Clamped to min
        self.assertEqual(result.scores["FPT"].score, 7)   # Converted to int

    @patch('requests.post')
    def test_json_response_validation(self, mock_post):
        """Test that JSON responses are properly validated."""
        # Mock successful HTTP response with valid JSON
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"scores": {"VHM": {"score": 8, "rationale": "Test", "risk_note": ""}}, "market_context": "Test"}'
                }
            }]
        }
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = _call_groq("test prompt", "test-key")

        self.assertIsInstance(result, dict)
        self.assertIn("scores", result)
        self.assertIn("market_context", result)

    @patch('requests.post')
    def test_invalid_json_response(self, mock_post):
        """Test handling of invalid JSON responses."""
        # Mock response with invalid JSON
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Invalid JSON response here"
                }
            }]
        }
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = _call_groq("test prompt", "test-key")

        # Should return None for invalid JSON
        self.assertIsNone(result)

    @patch('requests.post')
    @patch('src.ai.groq_analyzer._CACHE', {})  # Clear cache for test
    def test_rate_limit_handling(self, mock_post):
        """Test handling of rate limit responses."""
        # Mock rate limit response
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "10"}
        mock_response.json.return_value = {
            "error": {"message": "Rate limit exceeded"}
        }
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            # Should handle rate limit gracefully (mocked to not actually retry)
            with patch('time.sleep'):  # Mock sleep to speed up test
                result = _call_groq("test prompt", "test-key")

        # Should return None for rate limit after retries exhausted
        self.assertIsNone(result)


class TestNewsAIConfig(unittest.TestCase):
    """Test news AI configuration loading."""

    def test_config_file_exists(self):
        """Test that the news AI configuration file exists."""
        from pathlib import Path
        config_path = Path("config/news_ai.yml")
        self.assertTrue(config_path.exists(), "News AI config file should exist")

    def test_config_file_valid_yaml(self):
        """Test that the config file contains valid YAML."""
        import yaml
        from pathlib import Path

        config_path = Path("config/news_ai.yml")
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Check required keys
        self.assertIn("enabled", config)
        self.assertIn("model_extract", config)
        self.assertIn("model_digest", config)
        self.assertIn("max_symbols", config)
        self.assertIn("max_articles_per_symbol", config)

        # Check values
        self.assertIsInstance(config["enabled"], bool)
        self.assertEqual(config["model_extract"], "llama-3.1-8b-instant")
        self.assertEqual(config["model_digest"], "llama-3.3-70b-versatile")
        self.assertIsInstance(config["max_symbols"], int)
        self.assertIsInstance(config["max_articles_per_symbol"], int)


if __name__ == "__main__":
    unittest.main()