from __future__ import annotations

from typing import Any, Dict, List


def build_earnings_research_strategy(result: Dict[str, Any]) -> Dict[str, Any]:
    summary = result.get("earnings_summary", {}) if isinstance(result.get("earnings_summary"), dict) else {}
    key_metrics = result.get("key_metrics", {}) if isinstance(result.get("key_metrics"), dict) else {}
    guidance = result.get("guidance", {}) if isinstance(result.get("guidance"), dict) else {}
    beat_miss = result.get("beat_miss_analysis", {}) if isinstance(result.get("beat_miss_analysis"), dict) else {}

    revenue_actual = summary.get("revenue", {}).get("actual", "N/A") if isinstance(summary.get("revenue"), dict) else "N/A"
    eps_actual = summary.get("earnings_per_share", {}).get("eps", "N/A") if isinstance(summary.get("earnings_per_share"), dict) else "N/A"
    rev_growth = key_metrics.get("growth", {}).get("revenue_growth", "N/A") if isinstance(key_metrics.get("growth"), dict) else "N/A"
    earnings_growth = key_metrics.get("growth", {}).get("earnings_growth", "N/A") if isinstance(key_metrics.get("growth"), dict) else "N/A"
    gross_margin = key_metrics.get("profitability", {}).get("gross_margin", "N/A") if isinstance(key_metrics.get("profitability"), dict) else "N/A"
    operating_margin = key_metrics.get("profitability", {}).get("operating_margin", "N/A") if isinstance(key_metrics.get("profitability"), dict) else "N/A"

    results_status = "PENDING_VERIFICATION"
    if beat_miss.get("status") == "unavailable":
        results_status = "PENDING_VERIFICATION"

    key_takeaways = [
        f"Quarter revenue printed at {revenue_actual} with EPS at {eps_actual}.",
        f"Reported growth snapshot shows revenue growth {rev_growth} and earnings growth {earnings_growth}.",
        f"Profitability remains healthy with gross margin {gross_margin} and operating margin {operating_margin}.",
    ]

    thesis_scorecard: List[Dict[str, Any]] = [
        {
            "pillar": "Revenue growth durability",
            "original_expectation": "Sustain above-market growth after the latest quarter",
            "current_status": rev_growth,
            "trend": "stable" if rev_growth != "N/A" else "watch",
        },
        {
            "pillar": "Margin resilience",
            "original_expectation": "Maintain operating leverage through the cycle",
            "current_status": operating_margin,
            "trend": "stable" if operating_margin != "N/A" else "watch",
        },
        {
            "pillar": "Capital return / balance sheet support",
            "original_expectation": "Support valuation through cash generation and shareholder returns",
            "current_status": key_metrics.get("dividends", {}).get("dividend_yield", "N/A")
            if isinstance(key_metrics.get("dividends"), dict)
            else "N/A",
            "trend": "stable",
        },
    ]

    catalysts = [
        {
            "event": "Next earnings release",
            "expected_impact": "Validates whether the latest growth and margin trajectory is sustainable",
        },
        {
            "event": "Management guidance updates",
            "expected_impact": "Determines whether estimate revisions and price target changes are warranted",
        },
    ]

    return {
        "framework": "financial-services-plugins equity-research earnings-analysis + thesis-tracker",
        "earnings_summary_box": {
            "results_status": results_status,
            "reported_revenue": revenue_actual,
            "reported_eps": eps_actual,
            "key_takeaways": key_takeaways,
        },
        "investment_impact": {
            "rating_action": "maintain pending verified consensus and valuation update",
            "price_target_action": "no change implied without model refresh",
            "guidance_direction": guidance.get("direction", "Unknown"),
        },
        "thesis_scorecard": thesis_scorecard,
        "catalyst_calendar": catalysts,
        "model_update_trigger": {
            "trigger": "earnings release",
            "required_updates": [
                "plug actual quarterly revenue and EPS",
                "refresh forward assumptions from guidance",
                "reconcile valuation after estimate changes",
            ],
        },
        "notes": [
            "Derived research structure modeled on financial-services-plugins workflows.",
            "Not a published rating or target-price recommendation.",
        ],
    }
