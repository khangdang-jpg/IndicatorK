"""Bull Market Enhancement Recommendations for Institutional Intraweek Strategy

This file outlines specific parameter changes and code modifications to significantly
improve bull market performance from current 9.29% CAGR to target 20%+ CAGR.

Key Issues Identified:
1. Overly conservative trend detection (1.5% threshold)
2. Restrictive volume requirements for momentum trades
3. Conservative position sizing (18% max vs weekly system's larger positions)
4. Low Kelly multipliers despite high win rates

Target: Boost bull market CAGR from 9.29% to 20%+ while maintaining risk control
"""

# ENHANCEMENT 1: More Aggressive Bull Market Detection
ENHANCED_BULL_DETECTION = {
    # Current vs Enhanced parameters
    "trend_threshold": {
        "current": 0.015,  # 1.5% - too conservative
        "enhanced": 0.025,  # 2.5% - better bull detection
        "line": 78
    },
    "adx_trending_threshold": {
        "current": 12,     # Very low
        "enhanced": 18,    # More selective for real trends
        "line": 80
    },
    "momentum_rsi_min": {
        "current": 45,     # Too low - catches weak signals
        "enhanced": 52,    # Higher quality momentum entries
        "line": 83
    }
}

# ENHANCEMENT 2: Remove Volume Surge Requirement for Bull Markets
BULL_MARKET_ENTRY_LOGIC = {
    "description": "Remove restrictive volume requirements in strong bull trends",
    "current_logic": """
    # Line 854-855: Too restrictive
    if (is_uptrend and rsi >= momentum_threshold and has_conviction and
        (volume_surge or conviction_score > 0.8)):
    """,
    "enhanced_logic": """
    # Enhanced: Simpler, more aggressive bull entry
    if (is_uptrend and rsi >= momentum_threshold and has_conviction):
        # Volume surge becomes a bonus, not requirement
    """
}

# ENHANCEMENT 3: Significantly Higher Position Sizing
ENHANCED_POSITION_SIZING = {
    "bull_market_positions": {
        "current_max": 0.18,    # 18% max position
        "enhanced_max": 0.25,   # 25% max position (39% increase)
        "current_base": 0.15,   # 15% base position
        "enhanced_base": 0.20,  # 20% base position (33% increase)
        "line_references": [688, 892]
    },
    "kelly_multipliers": {
        "current_bull_mult": 2.0,    # Line 580
        "enhanced_bull_mult": 2.8,   # 40% increase (2.0→2.8)
        "rationale": "Weekly system captures 26.14% CAGR with larger positions"
    }
}

# ENHANCEMENT 4: More Aggressive Bull Market Parameters
BULL_MOMENTUM_PARAMS = {
    "momentum_atr_target": {
        "current": 4.0,      # Line 85
        "enhanced": 5.2,     # Higher targets in bull markets (30% increase)
        "justification": "Bull markets support higher targets"
    },
    "momentum_position_mult": {
        "current": 1.4,      # Line 86
        "enhanced": 1.8,     # More aggressive sizing (29% increase)
        "justification": "Match weekly system's bull market aggression"
    }
}

# ENHANCEMENT 5: Regime-Specific Strategy Selection Improvements
REGIME_STRATEGY_ENHANCEMENTS = {
    "bull_market_regime_detection": {
        "issue": "Current system might misclassify bull trends as sideways",
        "enhancement": "Lower the volatility threshold specifically for bull detection",
        "current_volatility_threshold": 0.30,  # Line 79
        "enhanced_bull_volatility": 0.35,      # Allow more volatility in bull trends
    }
}

# IMPLEMENTATION PRIORITY
IMPLEMENTATION_PLAN = {
    "phase_1_quick_wins": [
        "Increase bull market position sizing (lines 688, 892)",
        "Raise Kelly multiplier for trending_bull (line 580)",
        "Remove volume surge requirement for bull momentum (line 854)"
    ],
    "phase_2_parameter_tuning": [
        "Adjust trend_threshold to 2.5% (line 78)",
        "Increase momentum_atr_target to 5.2 (line 85)",
        "Raise momentum_position_mult to 1.8 (line 86)"
    ],
    "phase_3_advanced": [
        "Implement bull-specific RSI thresholds",
        "Add bull market momentum confirmation logic",
        "Optimize entry timing for strong trends"
    ]
}

# EXPECTED IMPACT
PERFORMANCE_PROJECTIONS = {
    "current_bull_performance": {
        "cagr": "9.29%",
        "trades": 4,
        "win_rate": "50.0%",
        "profit_factor": 1.78
    },
    "enhanced_bull_performance_target": {
        "cagr": "20-22%",  # 115% improvement
        "trades": "8-10",   # Double trade frequency
        "win_rate": "65%+", # Better signal quality
        "profit_factor": "2.5+"
    },
    "risk_controls": {
        "max_drawdown": "Keep under 6%",
        "position_size_caps": "Still apply 25% individual position limit",
        "stop_losses": "Maintain tight stops with higher targets"
    }
}

# CODE MODIFICATION LOCATIONS
SPECIFIC_CHANGES = {
    "file": "src/strategies/institutional_intraweek_enhanced.py",
    "critical_lines": {
        78: "trend_threshold: 0.015 → 0.025",
        80: "adx_trending_threshold: 12 → 18",
        83: "momentum_rsi_min: 45 → 52",
        85: "momentum_atr_target: 4.0 → 5.2",
        86: "momentum_position_mult: 1.4 → 1.8",
        580: "trending_bull multiplier: 2.0 → 2.8",
        688: "bull max position: 0.18 → 0.25",
        854: "Remove volume_surge requirement",
        892: "base position: 0.15 → 0.20"
    }
}