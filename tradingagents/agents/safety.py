"""Deterministic guardrails for LLM-produced trading research.

This module deliberately does not ask another model to judge whether a model
hallucinated.  It inspects graph-controlled provenance instead: every selected
analyst must have a non-empty report with an evidence ledger, and no source in
that ledger may be marked unavailable.  Failing closed is more useful than a
plausible but unsupported directional recommendation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_LEDGER = "## Evidence Ledger"
_ACTION_RE = re.compile(r"^\s*\*\*Action\*\*:\s*(Buy|Hold|Sell)\s*$", re.IGNORECASE | re.MULTILINE)
_NUMBER_RE = r"(?:\$|₹|€|£)?\s*(\d+(?:,\d{3})*(?:\.\d+)?)"


def _labelled_number(text: str, label: str) -> float | None:
    match = re.search(rf"^\s*\*\*{label}\*\*:\s*{_NUMBER_RE}\s*$", text,
                      re.IGNORECASE | re.MULTILINE)
    return float(match.group(1).replace(",", "")) if match else None


def order_readiness_summary(
    state: dict,
    max_position_pct: float,
    max_risk_per_trade_pct: float = 1.0,
    min_risk_reward_ratio: float = 2.0,
    max_daily_loss_pct: float = 2.0,
    daily_loss_used_pct: float = 0.0,
) -> str:
    """Audit an LLM proposal without trusting it to do the arithmetic.

    The framework intentionally has no broker adapter.  This audit therefore
    cannot authorize a live order; it shows whether a directional proposal has
    the minimum machine-checkable fields a human would need to review. Exact
    cash, quantity, lot size, brokerage, taxes, spread and live fill price are
    broker/account facts and are never invented here.
    """
    proposal = str(state.get("trader_investment_plan") or "")
    action_match = _ACTION_RE.search(proposal)
    action = action_match.group(1).title() if action_match else None
    problems: list[str] = []
    warnings = [
        "manual approval is required for every order",
        "live broker price, spread, liquidity, circuit/surveillance status, event risk, fees, taxes, lot rules and market hours are not verified",
    ]
    if state.get("asset_type", "stock") not in {"stock", "crypto"}:
        problems.append("only unlevered stock and crypto research is supported; futures and options are excluded")
    if daily_loss_used_pct >= max_daily_loss_pct:
        problems.append(
            f"reported daily loss {daily_loss_used_pct:g}% has reached the {max_daily_loss_pct:g}% limit"
        )
    if not action:
        problems.append("the trader action is missing or malformed")
    elif action != "Hold":
        entry = _labelled_number(proposal, "Entry Price")
        stop = _labelled_number(proposal, "Stop Loss")
        target = _labelled_number(proposal, "Take Profit")
        sizing_match = re.search(r"\*\*Position Sizing\*\*:\s*(\d+(?:\.\d+)?)\s*%",
                                 proposal, re.IGNORECASE)
        if entry is None or entry <= 0:
            problems.append("a positive numeric entry price is required")
        if stop is None or stop <= 0:
            problems.append("a positive numeric stop-loss is required")
        if target is None or target <= 0:
            problems.append("a positive numeric take-profit target is required")
        if entry and stop:
            if action == "Buy" and stop >= entry:
                problems.append("a Buy stop-loss must be below entry")
            if action == "Sell" and stop <= entry:
                problems.append("a Sell stop-loss must be above entry")
        if entry and target:
            if action == "Buy" and target <= entry:
                problems.append("a Buy take-profit target must be above entry")
            if action == "Sell" and target >= entry:
                problems.append("a Sell take-profit target must be below entry")
        if sizing_match is None:
            problems.append("a numeric percentage position size is required")
        else:
            size_pct = float(sizing_match.group(1))
            if size_pct > max_position_pct:
                problems.append(f"position size exceeds the configured {max_position_pct:g}% cap")
            if entry and stop:
                risk_pct = size_pct * abs(entry - stop) / entry
                if risk_pct > max_risk_per_trade_pct:
                    problems.append(
                        f"worst-case stop loss is {risk_pct:.2f}% of capital, above the {max_risk_per_trade_pct:g}% per-trade cap"
                    )
        if entry and stop and target and abs(entry - stop) > 0:
            reward_ratio = abs(target - entry) / abs(entry - stop)
            if reward_ratio < min_risk_reward_ratio:
                problems.append(
                    f"risk/reward ratio is {reward_ratio:.2f}, below the required {min_risk_reward_ratio:g}"
                )
        held_quantity = state.get("portfolio_position_quantity")
        average_price = state.get("portfolio_position_average_price")
        if held_quantity and average_price and entry:
            if action == "Buy" and held_quantity > 0 and entry < average_price:
                problems.append("adding below an existing long average price is blocked as averaging down")
            if action == "Sell" and held_quantity < 0 and entry > average_price:
                problems.append("adding above an existing short average price is blocked as averaging down")

    header = "## Execution Readiness"
    if problems:
        return "\n".join([
            header,
            "**Status:** NOT EXECUTION-READY.",
            "**Reason:** " + "; ".join(problems) + ".",
            "**Boundary:** TradingAgents is paper-only; no broker order can be sent from this run.",
            "**Manual checks:** " + "; ".join(warnings) + ".",
        ])
    return "\n".join([
        header,
        "**Status:** REVIEW REQUIRED.",
        "The proposal passes only basic numeric checks; it is not an execution authorization.",
        "**Boundary:** TradingAgents is paper-only; no broker order can be sent from this run.",
        "**Manual checks:** " + "; ".join(warnings) + ".",
    ])


def decision_safety_summary(state: dict, required_reports: Iterable[str]) -> tuple[bool, str]:
    """Return whether a decision is evidence-backed and a report-ready audit."""
    violations: list[str] = []
    checked: list[str] = []
    for report_key in required_reports:
        report = str(state.get(report_key) or "").strip()
        label = report_key.removesuffix("_report").replace("_", " ").title()
        if not report:
            violations.append(f"{label}: report is missing.")
            continue
        if _LEDGER not in report:
            violations.append(f"{label}: provenance ledger is missing.")
            continue
        ledger = report.split(_LEDGER, 1)[1].lower()
        if "no tool result was retrieved" in ledger or "unavailable" in ledger:
            violations.append(f"{label}: no usable retrieved evidence is recorded.")
            continue
        checked.append(label)

    if not str(state.get("final_trade_decision") or "").strip():
        violations.append("Portfolio Manager: final decision is missing.")

    if violations:
        return False, "\n".join([
            "## Decision Safety Check",
            "**Status:** BLOCKED — non-actionable research output.",
            "**Reason:** " + " ".join(violations),
            "Do not place an order from this run. Refresh the missing data and rerun the analysis.",
        ])

    return True, "\n".join([
        "## Decision Safety Check",
        "**Status:** PASSED — selected analyst inputs have recorded retrieved evidence.",
        "**Coverage:** " + ", ".join(checked) + ".",
        "This validates evidence retrieval, not the truth or future performance of LLM interpretation.",
    ])


def create_decision_safety_guard(
    required_reports: Iterable[str],
    enforce: bool = True,
    max_position_pct: float = 5.0,
    max_risk_per_trade_pct: float = 1.0,
    min_risk_reward_ratio: float = 2.0,
    max_daily_loss_pct: float = 2.0,
    daily_loss_used_pct: float = 0.0,
):
    """Create the final graph node that makes unsupported output non-actionable."""
    required_reports = tuple(required_reports)

    def guard(state: dict) -> dict:
        passed, summary = decision_safety_summary(state, required_reports)
        readiness = order_readiness_summary(
            state, max_position_pct, max_risk_per_trade_pct, min_risk_reward_ratio,
            max_daily_loss_pct, daily_loss_used_pct,
        )
        decision = str(state.get("final_trade_decision") or "").rstrip()
        if enforce and not passed:
            decision = "\n\n".join([
                summary,
                "**Rating**: Hold",
                "**Executive Summary**: Evidence requirements were not met; no trade is authorized by this research run.",
                "**Investment Thesis**: Re-run after the missing or unavailable evidence is retrieved and reviewed.",
            ])
            return {
                "decision_safety": summary,
                "execution_readiness": readiness,
                "final_trade_decision": decision,
                "final_rating": "Hold",
            }
        return {
            "decision_safety": summary,
            "execution_readiness": readiness,
            "final_trade_decision": f"{decision}\n\n{summary}",
        }

    return guard
