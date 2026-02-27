#!/usr/bin/env python
"""Convenience script: python scripts/backtest.py [args]

Equivalent to:  python -m src.backtest [args]
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so `src.*` imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.cli import main

if __name__ == "__main__":
    main()
