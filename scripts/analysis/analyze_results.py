import json

# Read all three summaries
with open('reports_tpsl_only/20260301_033843/summary.json') as f:
    tpsl = json.load(f)
with open('reports_3action/20260301_033847/summary.json') as f:
    action3 = json.load(f)
with open('reports_4action/20260301_033852/summary.json') as f:
    action4 = json.load(f)

print("=== RESULTS COMPARISON ===\n")
print(f"TPSL Only:")
print(f"  Final Value: {tpsl['final_value']:,.0f}")
print(f"  Trades: {tpsl['num_trades']}")
print(f"  Avg Invested: {tpsl['avg_invested_pct']:.1%}")
print(f"  Max DD: {tpsl['max_drawdown']:.1%}")
print()
print(f"3-Action:")
print(f"  Final Value: {action3['final_value']:,.0f}")
print(f"  Trades: {action3['num_trades']}")
print(f"  Avg Invested: {action3['avg_invested_pct']:.1%}")
print(f"  Max DD: {action3['max_drawdown']:.1%}")
print()
print(f"4-Action:")
print(f"  Final Value: {action4['final_value']:,.0f}")
print(f"  Trades: {action4['num_trades']}")
print(f"  Avg Invested: {action4['avg_invested_pct']:.1%}")
print(f"  Max DD: {action4['max_drawdown']:.1%}")
print()

# The key insight: 3action/4action have 94% invested (almost fully invested)
# vs tpsl_only with 30% invested. This means positions are held but never closed.
print("=== KEY INSIGHT ===")
print("3action/4action modes show 94% average invested (vs 30% for tpsl_only)")
print("This indicates positions were OPENED but NEVER CLOSED properly.")
print("\nThe strategy generates BUY signals → positions open")
print("But the weekly plan regeneration doesn't track open positions")
print("So SELL/REDUCE signals are never generated for existing positions")
print("\nResult: Buy-and-hold behavior instead of active management")
