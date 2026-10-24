# Safety boundaries

TradingAgents produces research, not executable orders. It has no broker
adapter, does not hold brokerage credentials, and every output is paper-only.
No combination of LLM prompts makes a prediction certain or appropriate for
unattended trading.

## Controls now enforced

| Risk | Control | Result when it fails |
| --- | --- | --- |
| Missing, failed, or stale-looking analyst inputs | Each analyst report gets a graph-generated evidence ledger. The final evidence gate requires usable evidence for every analyst selected for the run. | Final rating becomes `Hold` and the report is marked **BLOCKED**. |
| Invented identity or exact price claims | The graph resolves instrument identity once; market prompts require the verified snapshot before exact price claims. | Reports must name data that could not be retrieved; the evidence gate blocks no-data output. |
| Prompt injection in news, social posts, filings, or earlier reports | Every consuming agent is explicitly told that fetched content is untrusted data, not instructions. | The model is instructed to ignore role changes, secret requests, control bypasses and trade commands embedded in inputs. |
| Malformed LLM decisions | Research, trader and portfolio outputs use typed schemas where supported; ratings and numeric fields are parsed defensively. | An unparseable final rating is `REVIEW`, never a directional default. |
| Unsafe position suggestions | A deterministic readiness audit checks directional proposals for numeric entry, stop-loss, target, percentage size, stop/target direction, maximum size, risk per trade, reward/risk, daily-loss lockout, and averaging down when a supplied portfolio exposes an existing average price. | The report is **NOT EXECUTION-READY**. It is still never an order authorization. |
| Duplicate or unintended execution | No code path submits orders to a broker or exchange. | Not applicable: runs are paper-only. |
| Look-ahead in historical research | Dated tools are constrained to the requested date; SEC filing knowledge dates and point-in-time memory/backtests are used where the vendor supports them. | Unsupported historical data is withheld or labelled unavailable. |

## What remains outside this framework

The system cannot validate that a news item is true, forecast liquidity or
slippage, determine a broker's current fees/taxes/margin/circuit rules, or
eliminate model variance and regime-change risk. It also cannot know the
user's cash, lot constraints, tax position, or eligibility unless those facts
are supplied and independently verified.

Before a human places any order, they must independently check live broker
prices, bid/ask spread, liquidity, stop/limit semantics, costs and taxes,
position quantity, exchange restrictions, and their own risk plan. Backtests
measure historical behavior only; they are not evidence of a future edge.

## Configuration

The evidence gate is enabled by default. `TRADINGAGENTS_ENFORCE_EVIDENCE_GATE=false`
leaves the model rating intact for research/audit work but still records the
failure. The paper-trading limits are `TRADINGAGENTS_MAX_POSITION_PCT=5`,
`TRADINGAGENTS_MAX_RISK_PER_TRADE_PCT=1`,
`TRADINGAGENTS_MIN_RISK_REWARD_RATIO=2`, and
`TRADINGAGENTS_MAX_DAILY_LOSS_PCT=2`. Set
`TRADINGAGENTS_DAILY_LOSS_USED_PCT` only from a trusted, reconciled journal or
broker statement; this project never guesses it. Neither setting enables live
trading.
