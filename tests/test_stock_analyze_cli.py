from __future__ import annotations

from io import StringIO
import json
from typing import Any

from src.services.stock_analyze_cli import main as stock_analyze_cli_main
from src.services.stock_analyze_service import StockAnalyzeService


def _rows_payload(rows=None, status="ok", error=None):
    return {"rows": rows or [], "status": status, "error": error}


def _assert_no_subjective_keys(value):
    forbidden = {
        "recommendation",
        "confidence",
        "price_target",
        "moat_assessment",
        "thesis",
        "conviction",
        "positioning",
    }
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value.keys())
        for item in value.values():
            _assert_no_subjective_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_subjective_keys(item)


class FakeResearchProvider:
    def __init__(
        self,
        *,
        security=None,
        research_report=None,
        report_rc=None,
        anns_d=None,
        news=None,
        major_news=None,
    ):
        self.security = security or {"record": None, "status": "empty", "error": None}
        self.research_report = research_report or _rows_payload([], status="empty")
        self.report_rc = report_rc or _rows_payload([], status="empty")
        self.anns_d = anns_d or _rows_payload([], status="empty")
        self.news = news or {}
        self.major_news = major_news or {}

    def fetch_security_info(self, market, symbol):
        return dict(self.security)

    def fetch_research_report(self, **kwargs):
        return dict(self.research_report)

    def fetch_report_rc(self, **kwargs):
        return dict(self.report_rc)

    def fetch_anns_d(self, **kwargs):
        return dict(self.anns_d)

    def fetch_news(self, *, src, **kwargs):
        return dict(self.news.get(src, _rows_payload([], status="empty")))

    def fetch_major_news(self, *, src, **kwargs):
        return dict(self.major_news.get(src, _rows_payload([], status="empty")))


def _structured_module(
    service: StockAnalyzeService,
    *,
    status: str = "ok",
    error: str | None = None,
    reported: dict | None = None,
    consensus: dict | None = None,
    derived: dict | None = None,
    estimate: dict | None = None,
    model_output: dict | None = None,
    source: str = "test",
    limitations: list[str] | None = None,
    interface_type: str = "mixed",
) -> dict[str, Any]:
    analysis = {}
    if derived is not None:
        analysis["derived"] = derived
    if estimate is not None:
        analysis["estimate"] = estimate
    if model_output is not None:
        analysis["model_output"] = model_output
    payload = service._make_structured_payload(
        entity={"symbol": "TEST", "name": "Test"},
        facts={"reported": reported or {}, "consensus": consensus or {}},
        analysis=analysis,
        as_of=None,
        sources=[source],
        data_completeness="partial" if limitations else "ok",
        limitations=limitations or [],
        interface_type=interface_type,
    )
    return service._wrap_structured_module(
        payload=payload,
        status=status,
        error=error,
        attempted_sources=[source],
    )


def _technical_module(
    service: StockAnalyzeService,
    *,
    status: str = "ok",
    error: str | None = None,
) -> dict[str, Any]:
    if status != "ok":
        return _structured_module(
            service,
            status=status,
            error=error,
            source="stock_service",
            limitations=[error] if error else [],
        )
    return _structured_module(
        service,
        reported={
            "fear_greed": {"index": 65.0, "label": "偏贪婪"},
            "technical_signals": [
                {
                    "key": "trend",
                    "name": "趋势",
                    "status": "bullish",
                    "bullish_signals": ["价格站上 MA20/MA60"],
                    "bearish_signals": [],
                }
            ],
        },
        derived={
            "trend": {
                "trend_status": "多头排列",
                "trend_strength": 78.0,
                "buy_signal": "买入",
                "signal_score": 82,
            }
        },
        source="stock_service",
    )


def _cn_security_record(
    symbol: str = "600519", name: str = "贵州茅台", security_type: str = "stock"
):
    return {
        "symbol": symbol,
        "ts_code": f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ",
        "name": name,
        "exchange": "SSE" if symbol.startswith("6") else "SZSE",
        "list_status": "L",
        "area": "贵州",
        "industry": "白酒",
        "market": "主板",
        "list_date": "20010827",
        "security_type": security_type,
    }


def _us_security_info(symbol: str = "NVDA"):
    return {
        "record": {
            "symbol": symbol,
            "name": "NVIDIA",
            "exchange": "NASDAQ",
            "currency": "USD",
            "sector": "Technology",
            "industry": "Semiconductors",
            "security_type": "stock",
            "raw_data": {},
        },
        "status": "ok",
        "error": None,
        "attempted_sources": ["yfinance"],
        "info": {
            "common": {
                "ts_code": None,
                "name": "NVIDIA",
                "list_date": None,
                "delist_date": None,
            },
            "cn_specific": {
                "symbol": None,
                "exchange": None,
                "list_status": None,
                "area": None,
                "industry": None,
                "market": None,
            },
            "us_specific": {
                "ts_code": symbol,
                "name": "NVIDIA",
                "enname": None,
                "classify": "stock",
                "list_date": None,
                "delist_date": None,
            },
        },
    }


class FakeSymbolCatalog:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def search_symbols(self, keyword, market=None):
        self.calls.append({"keyword": keyword, "market": market})
        return list(self.results)


class FakeAnalyzeService:
    def __init__(self):
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "status": "ok",
            "computed_at": "2026-05-04T00:00:00+00:00",
            "source": "stock_analyze_dispatcher",
            "market": kwargs["market"],
            "strategy": "fsp_objective_stock_analyze_v2",
            "request": {
                "market": kwargs["market"],
                "symbols": list(kwargs["symbols"]),
                "start_date": kwargs.get("start_date"),
                "end_date": kwargs.get("end_date"),
                "mode": kwargs.get("mode"),
            },
            "items": [{"requested_symbol": symbol, "status": "ok"} for symbol in kwargs["symbols"]],
        }


def _run_cli(service: StockAnalyzeService, *args: str, symbol_catalog=None) -> dict[str, Any]:
    writer = StringIO()
    payload = stock_analyze_cli_main(
        list(args),
        writer=writer,
        service=service,
        symbol_catalog=symbol_catalog,
    )
    written = json.loads(writer.getvalue())
    assert written == payload
    return payload


class TestStockAnalyzeCli:
    def test_cli_resolves_cn_stock_name_before_analyze(self):
        service = FakeAnalyzeService()
        catalog = FakeSymbolCatalog(
            [
                {
                    "symbol": "300750",
                    "ts_code": "300750.SZ",
                    "name": "宁德时代",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "cnspell": "NDSD",
                }
            ]
        )

        payload = _run_cli(
            service,
            "--market",
            "cn",
            "--symbols",
            "宁德时代",
            "--mode",
            "full",
            symbol_catalog=catalog,
        )

        assert catalog.calls == [{"keyword": "宁德时代", "market": "cn"}]
        assert service.calls[0]["symbols"] == ["300750"]
        assert payload["data"]["request"]["symbols"] == ["300750"]

    def test_cli_returns_identity_conflict_for_ambiguous_stock_name(self):
        service = FakeAnalyzeService()
        catalog = FakeSymbolCatalog(
            [
                {"symbol": "300750", "ts_code": "300750.SZ", "name": "宁德时代"},
                {"symbol": "300751", "ts_code": "300751.SZ", "name": "宁德科技"},
            ]
        )

        payload = _run_cli(
            service,
            "--market",
            "cn",
            "--symbols",
            "宁德",
            symbol_catalog=catalog,
        )

        assert service.calls == []
        item = payload["data"]["items"][0]
        assert item["status"] == "failed"
        assert item["error"]["code"] == "identity_conflict"
        assert [candidate["symbol"] for candidate in item["error"]["candidates"]] == [
            "300750",
            "300751",
        ]

    def test_cn_base_cli_contract(self, monkeypatch):
        provider = FakeResearchProvider(
            security={"record": _cn_security_record(), "status": "ok", "error": None},
            research_report=_rows_payload(
                [
                    {
                        "trade_date": "20260326",
                        "inst_csname": "中信证券",
                        "title": "更新覆盖",
                        "report_type": "公司研究",
                    }
                ]
            ),
            report_rc=_rows_payload(
                [
                    {
                        "report_date": "20260327",
                        "quarter": "2026Q4",
                        "org_name": "中信证券",
                        "report_title": "盈利预测",
                        "rating": "买入",
                        "report_type": "点评",
                    }
                ]
            ),
            anns_d=_rows_payload(
                [
                    {
                        "ann_date": "20260325",
                        "rec_time": "2026-03-25 10:00:00",
                        "title": "董事会决议公告",
                    }
                ]
            ),
        )
        service = StockAnalyzeService(providers={"tushare": provider})
        monkeypatch.setattr(
            service, "_build_technical_module", lambda **kwargs: _technical_module(service)
        )
        monkeypatch.setattr(
            service,
            "_build_cn_earnings_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"financial_report": {"report_date": "20260327"}},
                derived={
                    "fundamentals": {"status": "covered"},
                    "growth": {"revenue_yoy": 12.0, "roe": 15.0, "summary": "revenue_yoy=1200.00%"},
                    "valuation": {"pe_ratio": 25.4},
                    "coverage": {"analyst_count": 3},
                },
                source="financial_provider",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                service,
                reported={
                    "metrics": {
                        "pe_ratio": 25.4,
                        "revenue_growth": 12.0,
                        "roe": 15.0,
                        "_source": "financial_provider",
                    }
                },
                derived={"filters": {}, "passed": True, "filter_count": 0},
                source="financial_provider",
            ),
        )

        payload = _run_cli(
            service,
            "--market",
            "cn",
            "--symbols",
            "600519",
            "--start-date",
            "20260301",
            "--end-date",
            "20260328",
            "--mode",
            "base",
            "--pretty",
        )

        assert payload["status_code"] == 200
        data = payload["data"]
        assert data["source"] == "stock_analyze_dispatcher"
        assert data["strategy"] == "fsp_objective_stock_analyze_v2"
        item = data["items"][0]
        assert item["status"] == "ok"
        assert set(item.keys()) >= {
            "requested_symbol",
            "info",
            "summary",
            "technical",
            "research_report",
            "report_rc",
            "earnings",
            "catalysts",
            "screen",
            "meta",
        }
        assert set(item["summary"].keys()) >= {
            "research_strategy",
            "research",
            "earnings",
            "catalysts",
            "screen",
            "change_flags",
            "technical",
        }
        assert item["technical"]["fear_greed"]["label"] == "greed"
        assert item["technical"]["trend"]["stance"] == "bullish_confirmation"
        assert "buy_signal" not in item["technical"]["trend"]
        assert item["technical"]["trend"]["methodology_version"] == "technical_research_v2"
        assert item["summary"]["technical"]["signal_count"] == 1
        assert item["summary"]["technical"]["trend"]["stance"] == "bullish_confirmation"
        assert item["summary"]["research"]["latest_estimate_date"] == "20260327"
        assert item["summary"]["earnings"]["latest_report_date"] == "20260327"
        assert item["summary"]["catalysts"]["event_count"] == 1
        assert item["summary"]["screen"]["evaluated"] is False
        assert item["summary"]["screen"]["passed"] is None
        assert item["earnings"]["growth"]["revenue_yoy"] == 0.12
        assert item["earnings"]["growth"]["roe"] == 0.15
        assert "summary" not in item["earnings"]["growth"]
        assert item["screen"]["metrics"]["revenue_growth"] == 0.12
        assert item["screen"]["metrics"]["roe"] == 0.15
        strategy_summary = item["summary"]["research_strategy"]
        assert set(strategy_summary.keys()) >= {
            "expectations_vs_reported",
            "fundamental_quality",
            "valuation_context",
            "catalyst_path",
            "price_action_confirmation",
            "cross_signal_alignment",
            "risk_flags",
            "evidence_strength",
        }
        assert strategy_summary["price_action_confirmation"]["stance"] == "bullish_confirmation"
        provenance = item["meta"]["provenance"]["summary"]["research_strategy"]
        assert set(provenance.keys()) >= {
            "expectations_vs_reported",
            "fundamental_quality",
            "valuation_context",
            "catalyst_path",
            "price_action_confirmation",
            "cross_signal_alignment",
            "risk_flags",
            "evidence_strength",
        }
        assert provenance["price_action_confirmation"]["source_modules"] == ["technical"]
        _assert_no_subjective_keys(data)

    def test_cn_full_degraded_raw_blocks_only_live_in_meta(self, monkeypatch):
        provider = FakeResearchProvider(
            security={
                "record": _cn_security_record(symbol="300827", name="上能电气"),
                "status": "ok",
                "error": None,
            },
            research_report=_rows_payload(
                [{"trade_date": "20260326", "inst_csname": "华安证券", "title": "更新覆盖"}]
            ),
            report_rc=_rows_payload(
                [
                    {
                        "report_date": "20260327",
                        "quarter": "2026Q4",
                        "org_name": "华安证券",
                        "report_title": "盈利预测",
                        "rating": "买入",
                        "report_type": "点评",
                    }
                ]
            ),
            anns_d=_rows_payload([], status="permission_denied", error="permission denied"),
            news={"cls": _rows_payload([], status="empty")},
            major_news={
                "财联社": _rows_payload([], status="permission_denied", error="permission denied")
            },
        )
        service = StockAnalyzeService(providers={"tushare": provider})
        monkeypatch.setattr(
            service, "_build_technical_module", lambda **kwargs: _technical_module(service)
        )
        monkeypatch.setattr(
            service,
            "_build_cn_earnings_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"financial_report": {"report_date": "20260327"}},
                derived={"growth": {"revenue_yoy": 0.18}, "valuation": {"pe_ratio": 30.1}},
                source="financial_provider",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"metrics": {"pe_ratio": 30.1, "_source": "financial_provider"}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
                source="financial_provider",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_model_update_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"input_overrides": {}},
                derived={"refreshed_modules": {"earnings": "ok"}},
                source="stock_analyze_dispatcher",
            ),
        )

        payload = _run_cli(
            service,
            "--market",
            "cn",
            "--symbols",
            "300827",
            "--mode",
            "full",
        )

        item = payload["data"]["items"][0]
        assert item["status"] == "partial"
        assert "anns_d" not in item
        assert "news" not in item
        assert "major_news" not in item
        assert item["meta"]["modules"]["anns_d"]["status"] == "permission_denied"
        assert item["meta"]["modules"]["news"]["status"] == "empty"
        assert item["meta"]["modules"]["major_news"]["status"] == "permission_denied"
        assert "model_update" in item
        assert "research_strategy" in item["summary"]
        assert "provenance" in item["meta"]
        _assert_no_subjective_keys(payload["data"])

    def test_us_base_cli_contract(self, monkeypatch):
        service = StockAnalyzeService(providers={})
        monkeypatch.setattr(
            service, "_fetch_us_security_info", lambda symbol: _us_security_info(symbol)
        )
        monkeypatch.setattr(
            service, "_build_technical_module", lambda **kwargs: _technical_module(service)
        )
        monkeypatch.setattr(
            service,
            "_build_us_earnings_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"quarter": "Q4", "eps_actual": 1.2},
                consensus={"eps_estimate": 1.1},
                derived={"growth": {"revenue_yoy": 0.21}, "coverage": {"analyst_count": 28}},
                source="yfinance",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_dcf_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"assumptions": {"wacc": 0.09}},
                model_output={"equity_value_per_share": 120.5},
                source="yfinance",
                interface_type="model",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_comps_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"peer_set": [{"symbol": "AMD"}]},
                derived={"valuation_gap": {"median_pe_ratio": 35.0}},
                source="yfinance",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_three_statement_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"historical_revenue": [100, 120]},
                model_output={"projected_revenue": [130, 145]},
                source="yfinance",
                interface_type="model",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"metrics": {"market_cap": 1000000000.0, "_source": "yfinance"}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
                source="yfinance",
            ),
        )

        payload = _run_cli(
            service,
            "--market",
            "us",
            "--symbols",
            "NVDA",
            "--mode",
            "base",
        )

        item = payload["data"]["items"][0]
        assert item["status"] == "ok"
        assert set(item.keys()) >= {
            "technical",
            "earnings",
            "dcf",
            "comps",
            "three_statement",
            "screen",
        }
        assert set(item["summary"].keys()) >= {
            "research_strategy",
            "technical",
            "earnings",
            "screen",
            "models",
        }
        assert item["technical"]["fear_greed"]["label"] == "greed"
        assert item["technical"]["trend"]["stance"] == "bullish_confirmation"
        assert item["summary"]["screen"]["evaluated"] is False
        assert item["summary"]["screen"]["passed"] is None
        assert (
            item["summary"]["research_strategy"]["valuation_context"]["model_status"]["dcf"] == "ok"
        )
        assert item["meta"]["provenance"]["summary"]["research_strategy"]["valuation_context"][
            "source_modules"
        ] == ["earnings", "dcf", "comps", "three_statement"]
        assert item["meta"]["modules"]["dcf"]["status"] == "ok"
        _assert_no_subjective_keys(payload["data"])

    def test_invalid_symbol_cli_returns_failed_item(self):
        service = StockAnalyzeService(providers={"tushare": FakeResearchProvider()})

        payload = _run_cli(
            service,
            "--market",
            "cn",
            "--symbols",
            "BAD",
        )

        item = payload["data"]["items"][0]
        assert item["status"] == "failed"
        assert item["error"]["code"] == "invalid_symbol"

    def test_not_supported_cli_returns_not_supported_item(self):
        provider = FakeResearchProvider(
            security={
                "record": _cn_security_record(
                    symbol="510300", name="沪深300ETF", security_type="etf"
                ),
                "status": "ok",
                "error": None,
            }
        )
        service = StockAnalyzeService(providers={"tushare": provider})

        payload = _run_cli(
            service,
            "--market",
            "cn",
            "--symbols",
            "510300",
        )

        item = payload["data"]["items"][0]
        assert item["status"] == "not_supported"
        assert item["error"]["code"] == "security_not_supported"

    def test_core_unavailable_cli_marks_item_failed(self, monkeypatch):
        provider = FakeResearchProvider(
            security={"record": _cn_security_record(), "status": "ok", "error": None},
            research_report=_rows_payload(
                [{"trade_date": "20260326", "inst_csname": "中信证券", "title": "更新覆盖"}]
            ),
            report_rc=_rows_payload(
                [
                    {
                        "report_date": "20260327",
                        "quarter": "2026Q4",
                        "org_name": "中信证券",
                        "report_title": "盈利预测",
                        "rating": "买入",
                        "report_type": "点评",
                    }
                ]
            ),
        )
        service = StockAnalyzeService(providers={"tushare": provider})
        monkeypatch.setattr(
            service,
            "_build_technical_module",
            lambda **kwargs: _technical_module(service, status="error", error="technical failed"),
        )
        monkeypatch.setattr(
            service,
            "_build_cn_earnings_module",
            lambda **kwargs: _structured_module(
                service, reported={"financial_report": {}}, source="financial_provider"
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                service,
                reported={"metrics": {"pe_ratio": 25.4, "_source": "financial_provider"}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
                source="financial_provider",
            ),
        )

        payload = _run_cli(
            service,
            "--market",
            "cn",
            "--symbols",
            "600519",
        )

        item = payload["data"]["items"][0]
        assert item["status"] == "failed"
        assert item["meta"]["modules"]["technical"]["status"] == "error"
        assert "research_strategy" in item["summary"]
        assert "provenance" in item["meta"]
