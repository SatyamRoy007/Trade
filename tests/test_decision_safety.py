"""The evidence gate must be deterministic and fail closed."""

import pytest

from tradingagents.agents.safety import create_decision_safety_guard, decision_safety_summary


@pytest.mark.unit
def test_gate_passes_only_reports_with_retrieved_provenance():
    state = {
        "market_report": "trend data\n\n## Evidence Ledger\n- `get_stock_data`: retrieved",
        "news_report": "headlines\n\n## Evidence Ledger\n- `get_news`: retrieved",
        "final_trade_decision": "**Rating**: Buy",
        "final_rating": "Buy",
    }

    passed, summary = decision_safety_summary(state, ("market_report", "news_report"))

    assert passed
    assert "PASSED" in summary


@pytest.mark.unit
def test_gate_blocks_an_unavailable_or_missing_source_and_replaces_directional_call():
    state = {
        "market_report": "no data\n\n## Evidence Ledger\nNo tool result was retrieved; this report must not support a trade decision.",
        "final_trade_decision": "**Rating**: Buy\nBuy immediately.",
        "final_rating": "Buy",
    }

    result = create_decision_safety_guard(("market_report",), enforce=True)(state)

    assert result["final_rating"] == "Hold"
    assert "BLOCKED" in result["decision_safety"]
    assert "**Rating**: Hold" in result["final_trade_decision"]


@pytest.mark.unit
def test_audit_only_mode_keeps_the_rating_but_records_the_failure():
    state = {
        "market_report": "report with no ledger",
        "final_trade_decision": "**Rating**: Sell",
        "final_rating": "Sell",
    }

    result = create_decision_safety_guard(("market_report",), enforce=False)(state)

    assert result.get("final_rating") is None
    assert result["final_trade_decision"].startswith("**Rating**: Sell")
    assert "BLOCKED" in result["decision_safety"]


@pytest.mark.unit
def test_directional_proposal_without_a_stop_or_size_is_not_execution_ready():
    state = {"trader_investment_plan": "**Action**: Buy\n\n**Entry Price**: 100"}

    result = create_decision_safety_guard(("market_report",), enforce=False)(state)

    assert "NOT EXECUTION-READY" in result["execution_readiness"]
    assert "paper-only" in result["execution_readiness"]


@pytest.mark.unit
def test_directional_proposal_has_deterministic_stop_and_position_cap_checks():
    state = {
        "trader_investment_plan": (
            "**Action**: Buy\n\n**Entry Price**: 100\n\n**Stop Loss**: 95"
            "\n\n**Position Sizing**: 8% of portfolio"
        ),
    }

    result = create_decision_safety_guard(("market_report",), enforce=False,
                                          max_position_pct=5.0)(state)

    assert "exceeds the configured 5% cap" in result["execution_readiness"]


@pytest.mark.unit
def test_risk_policy_enforces_reward_ratio_and_daily_loss_limit():
    state = {
        "trader_investment_plan": (
            "**Action**: Buy\n\n**Entry Price**: 100\n\n**Stop Loss**: 90"
            "\n\n**Take Profit**: 105\n\n**Position Sizing**: 5% of portfolio"
        ),
    }

    result = create_decision_safety_guard(
        ("market_report",), enforce=False, max_daily_loss_pct=2.0, daily_loss_used_pct=2.0,
    )(state)

    audit = result["execution_readiness"]
    assert "risk/reward ratio is 0.50" in audit
    assert "daily loss 2% has reached the 2% limit" in audit


@pytest.mark.unit
def test_averaging_down_is_blocked_when_the_portfolio_supplies_an_average_price():
    state = {
        "portfolio_position_quantity": 10,
        "portfolio_position_average_price": 100,
        "trader_investment_plan": (
            "**Action**: Buy\n\n**Entry Price**: 90\n\n**Stop Loss**: 85"
            "\n\n**Take Profit**: 100\n\n**Position Sizing**: 2% of portfolio"
        ),
    }

    result = create_decision_safety_guard(("market_report",), enforce=False)(state)

    assert "blocked as averaging down" in result["execution_readiness"]
