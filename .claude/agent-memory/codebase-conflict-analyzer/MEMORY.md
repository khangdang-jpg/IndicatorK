# Codebase Conflict Analyzer Memory

## Project: IndicatorK - Python Trading Bot

### Key Architecture Patterns
- **Weekly workflow split**: Run technical AI analysis in `run_weekly.py`, send separate message via `run_ai_analysis.py`
- **Data persistence**: AI results cached in `data/weekly_plan.json` (fields: `ai_analysis`, `news_analysis`)
- **Telegram formatter**: Multiple formatting functions with overlapping responsibilities
- **GitHub Actions**: Sequential workflows - `weekly.yml` → `ai_analysis.yml`

### Common Conflict Patterns
1. **Duplicate formatting logic**: `_format_unified_analysis()` vs `format_ai_analysis_message()` - both format AI+news scores
2. **Unused imports**: After refactoring, check for orphaned imports (e.g., `SimpleNamespace`, model classes)
3. **Default parameter conflicts**: Functions with `include_analysis=True` default may affect existing callers
4. **Data reconstruction**: JSON→dataclass conversion must handle all optional fields (`news_analysis`, etc.)

### File Locations
- Scripts: `/Users/khangdang/IndicatorK/scripts/`
- Formatters: `/Users/khangdang/IndicatorK/src/telegram/formatter.py`
- Models: `/Users/khangdang/IndicatorK/src/models.py`
- AI analyzers: `/Users/khangdang/IndicatorK/src/ai/groq_analyzer.py`
- News AI: `/Users/khangdang/IndicatorK/src/news_ai/`
- Workflows: `/Users/khangdang/IndicatorK/.github/workflows/`

### Known Issues (from recent refactor)
- `PortfolioStateManager` imported but never used in `run_weekly.py` (line 37)
- `format_plan_summary()` has AI section that may be stale after split
- Need to verify `include_analysis` default doesn't break `/plan` command
