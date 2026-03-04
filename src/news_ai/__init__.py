"""News AI module using Groq API for market sentiment analysis."""

from .groq_client import extract_news_scores, compose_weekly_digest, is_available
from .groq_buy_potential import score_buy_potential

__all__ = ["extract_news_scores", "compose_weekly_digest", "is_available", "score_buy_potential"]