.PHONY: setup test run_alerts_once run_weekly_once run_bot_once lint backtest

setup:
	pip install -r requirements.txt

test:
	python -m pytest tests/ -v

run_alerts_once:
	python scripts/run_alerts.py

run_weekly_once:
	python scripts/run_weekly.py

run_bot_once:
	python scripts/run_bot.py

lint:
	python -m py_compile src/models.py
	python -m py_compile src/utils/config.py
	python -m py_compile src/utils/trading_hours.py
	python -m py_compile src/utils/csv_safety.py
	python -m py_compile src/providers/base.py
	python -m py_compile src/providers/composite_provider.py
	python -m py_compile src/strategies/base.py
	python -m py_compile src/portfolio/engine.py
	python -m py_compile src/guardrails/engine.py
	python -m py_compile src/backtest/engine.py
	python -m py_compile src/backtest/weekly_generator.py
	python -m py_compile src/backtest/reporter.py
	python -m py_compile src/backtest/cli.py
	@echo "All modules compile OK"

# ---------------------------------------------------------------------------
# Backtest: Evaluate weekly strategies against 2025-05-01 to 2026-02-25
# ---------------------------------------------------------------------------
# SPEC: 10M VND initial capital, 1M VND per trade, 4 trades/week
# Required: FROM, TO
# Optional: INITIAL_CASH (default 10000000), ORDER_SIZE (default 1000000),
#           TRADES_PER_WEEK (default 4), TIE_BREAKER (default worst),
#           MODE (default generate), PLAN_FILE, UNIVERSE
# Flags:    RUN_RANGE=1  → run both worst+best and write range_summary.json
#
# Examples:
#   make backtest FROM=2025-05-01 TO=2026-02-25
#   make backtest FROM=2025-05-01 TO=2026-02-25 ORDER_SIZE=1000000 RUN_RANGE=1
#   make backtest FROM=2025-05-01 TO=2026-02-25 TRADES_PER_WEEK=2

FROM         ?=
TO           ?=
INITIAL_CASH ?= 10000000
ORDER_SIZE   ?= 1000000
TRADES_PER_WEEK ?= 4
TIE_BREAKER  ?= worst
MODE         ?= generate
PLAN_FILE    ?= data/weekly_plan.json
UNIVERSE     ?= data/watchlist.txt
RUN_RANGE    ?=

backtest:
	@if [ -z "$(FROM)" ] || [ -z "$(TO)" ]; then \
		echo "Usage: make backtest FROM=YYYY-MM-DD TO=YYYY-MM-DD [OPTIONS]"; \
		echo "  INITIAL_CASH=10000000  ORDER_SIZE=1000000  TRADES_PER_WEEK=4"; \
		echo "  TIE_BREAKER=worst|best  MODE=generate|plan  RUN_RANGE=1"; \
		exit 1; \
	fi
	python3 scripts/backtest.py \
		--from $(FROM) \
		--to $(TO) \
		--initial-cash $(INITIAL_CASH) \
		--order-size $(ORDER_SIZE) \
		--trades-per-week $(TRADES_PER_WEEK) \
		--mode $(MODE) \
		--plan-file $(PLAN_FILE) \
		--universe $(UNIVERSE) \
		$(if $(RUN_RANGE),--run-range,--tie-breaker $(TIE_BREAKER))
