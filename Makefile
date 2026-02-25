.PHONY: setup test run_alerts_once run_weekly_once run_bot_once lint

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
	@echo "All modules compile OK"
