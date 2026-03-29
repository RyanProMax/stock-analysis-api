from __future__ import annotations

from io import StringIO
import importlib
import json

from src.analyzer.dcf_model import DCFModel
from src.data_provider.sources.yfinance import YfinanceDataSource
from src.services.research_snapshot_cli import main as research_snapshot_cli_main
from src.services.research_snapshot_service import ResearchSnapshotService

research_snapshot_module = importlib.import_module("src.services.research_snapshot_service")


def _rows_payload(rows=None, status="ok", error=None):
    return {"rows": rows or [], "status": status, "error": error}


def _structured_module(
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
):
    analysis = {}
    if derived is not None:
        analysis["derived"] = derived
    if estimate is not None:
        analysis["estimate"] = estimate
    if model_output is not None:
        analysis["model_output"] = model_output
    return {
        "entity": {"symbol": "TEST", "name": "Test"},
        "facts": {"reported": reported or {}, "consensus": consensus or {}},
        "analysis": analysis,
        "meta": {
            "schema_version": "2.0.0",
            "as_of": None,
            "sources": [source],
            "data_completeness": "partial" if limitations else "ok",
            "limitations": limitations or [],
            "interface_type": "mixed",
        },
        "module_status": status,
        "module_error": error,
        "attempted_sources": [source],
    }


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


class FakeSnapshotService:
    def __init__(self):
        self.calls = []

    def poll_snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "ok",
            "computed_at": "2026-03-29T00:00:00+00:00",
            "source": "research_snapshot_dispatcher",
            "market": kwargs["market"],
            "strategy": "fsp_objective_research_snapshot_v1",
            "request": kwargs,
            "items": [],
        }


class TestResearchSnapshotService:
    def test_cn_base_snapshot_uses_mode_summary_and_meta(self, monkeypatch):
        provider = FakeResearchProvider(
            security={
                "record": {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "exchange": "SSE",
                    "list_status": "L",
                    "area": "贵州",
                    "industry": "白酒",
                    "market": "主板",
                    "list_date": "20010827",
                    "security_type": "stock",
                },
                "status": "ok",
                "error": None,
            },
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
            news={
                "cls": _rows_payload(
                    [
                        {
                            "datetime": "2026-03-24 09:30:00",
                            "title": "贵州茅台盘中走强",
                            "content": "贵州茅台 600519 今日高开。",
                            "src": "cls",
                        }
                    ]
                )
            },
            major_news={
                "财联社": _rows_payload(
                    [
                        {
                            "pub_time": "2026-03-23 08:00:00",
                            "title": "贵州茅台发布渠道新动作",
                            "content": "贵州茅台 表示将优化渠道。",
                            "src": "财联社",
                        }
                    ]
                )
            },
        )
        service = ResearchSnapshotService(providers={"tushare": provider})
        monkeypatch.setattr(
            service,
            "_build_cn_earnings_module",
            lambda **kwargs: _structured_module(
                reported={"financial_report": {"report_date": "20260327"}},
                derived={
                    "fundamentals": {"status": "covered"},
                    "growth": {"revenue_yoy": 0.12},
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
                reported={"metrics": {"pe_ratio": 25.4, "_source": "financial_provider"}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
                source="financial_provider",
            ),
        )

        payload = service.poll_snapshot(
            market="cn",
            symbols=["600519"],
            start_date="20260301",
            end_date="20260328",
        )

        assert payload["status"] == "ok"
        assert payload["request"]["mode"] == "base"
        item = payload["items"][0]
        assert item["status"] == "ok"
        assert "derived" not in item
        assert item["meta"]["mode"] == "base"
        assert set(item["meta"]["modules"].keys()) == {
            "research_report",
            "report_rc",
            "earnings",
            "catalysts",
            "screen",
        }
        assert item["research_report"]["records"][0]["title"] == "更新覆盖"
        assert item["report_rc"]["records"][0]["report_title"] == "盈利预测"
        assert item["earnings"]["growth"]["revenue_yoy"] == 0.12
        assert item["screen"]["passed"] is True
        assert item["summary"]["research"]["report_count"] == 1
        assert item["summary"]["research"]["latest_estimate_date"] == "20260327"
        assert item["summary"]["change_flags"]["has_new_report_7d"] is True
        assert item["summary"]["catalysts"]["event_count"] == 3
        assert item["info"]["common"]["ts_code"] == "600519.SH"
        _assert_no_subjective_keys(payload)

    def test_cn_full_permission_denied_block_moves_to_meta_only(self, monkeypatch):
        provider = FakeResearchProvider(
            security={
                "record": {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "security_type": "stock",
                },
                "status": "ok",
                "error": None,
            },
            research_report=_rows_payload([], status="empty"),
            report_rc=_rows_payload([], status="empty"),
            news={"cls": _rows_payload([], status="permission_denied", error="权限不足")},
        )
        service = ResearchSnapshotService(providers={"tushare": provider})
        monkeypatch.setattr(
            service, "_build_cn_earnings_module", lambda **kwargs: _structured_module()
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                reported={"metrics": {"pe_ratio": 20}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
            ),
        )

        payload = service.poll_snapshot(market="cn", symbols=["600519"], mode="full")

        item = payload["items"][0]
        assert payload["status"] == "partial"
        assert item["status"] == "partial"
        assert "news" not in item
        assert item["meta"]["modules"]["news"]["status"] == "permission_denied"
        assert item["meta"]["modules"]["catalysts"]["status"] == "partial"
        assert item["meta"]["modules"]["catalysts"]["notes"]["limitations"]

    def test_core_permission_denied_marks_failed(self, monkeypatch):
        provider = FakeResearchProvider(
            security={
                "record": {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "security_type": "stock",
                },
                "status": "ok",
                "error": None,
            },
            research_report=_rows_payload([], status="permission_denied", error="权限不足"),
            report_rc=_rows_payload(
                [
                    {
                        "report_date": "20260301",
                        "report_title": "贵州茅台点评",
                        "report_type": "点评",
                        "quarter": "2026Q4",
                        "org_name": "中信证券",
                    }
                ]
            ),
        )
        service = ResearchSnapshotService(providers={"tushare": provider})
        monkeypatch.setattr(
            service, "_build_cn_earnings_module", lambda **kwargs: _structured_module()
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                reported={"metrics": {"pe_ratio": 20}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
            ),
        )

        payload = service.poll_snapshot(market="cn", symbols=["600519"])

        item = payload["items"][0]
        assert item["status"] == "failed"
        assert item["error"]["code"] == "core_module_unavailable"
        assert "research_report" not in item
        assert item["meta"]["modules"]["research_report"]["status"] == "permission_denied"

    def test_invalid_symbol_failed_shape(self):
        service = ResearchSnapshotService(providers={"tushare": FakeResearchProvider()})

        payload = service.poll_snapshot(market="cn", symbols=["BAD"])

        item = payload["items"][0]
        assert item["status"] == "failed"
        assert item["error"]["code"] == "invalid_symbol"
        assert item["summary"] == {}
        assert "research_report" not in item
        assert item["meta"]["mode"] == "base"
        assert item["meta"]["modules"]["research_report"]["status"] == "error"

    def test_etf_symbol_not_supported(self):
        provider = FakeResearchProvider(
            security={
                "record": {
                    "symbol": "510300",
                    "ts_code": "510300.SH",
                    "name": "沪深300ETF",
                    "market": "ETF",
                    "security_type": "etf",
                },
                "status": "ok",
                "error": None,
            }
        )
        service = ResearchSnapshotService(providers={"tushare": provider})

        payload = service.poll_snapshot(market="cn", symbols=["510300"])

        item = payload["items"][0]
        assert item["status"] == "not_supported"
        assert "report_rc" not in item
        assert item["meta"]["modules"]["report_rc"]["status"] == "not_supported"

    def test_report_rc_fallback_notes_live_in_meta(self, monkeypatch):
        provider = FakeResearchProvider(
            security={
                "record": {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "security_type": "stock",
                },
                "status": "ok",
                "error": None,
            },
            report_rc=_rows_payload(
                [
                    {
                        "report_date": "20260302",
                        "report_title": "行业专题",
                        "report_type": "非个股",
                        "quarter": "2026Q4",
                        "org_name": "东吴证券",
                    }
                ]
            ),
        )

        def report_rc_with_history(**kwargs):
            if "start_date" in kwargs or "end_date" in kwargs:
                return {
                    "rows": [
                        {
                            "report_date": "20260302",
                            "report_title": "行业专题",
                            "report_type": "非个股",
                            "quarter": "2026Q4",
                            "org_name": "东吴证券",
                        }
                    ],
                    "status": "ok",
                    "error": None,
                }
            return {
                "rows": [
                    {
                        "report_date": "20251105",
                        "report_title": "上能电气：营收稳健增长",
                        "report_type": "点评",
                        "quarter": "2026Q4",
                        "org_name": "华安证券",
                    }
                ],
                "status": "ok",
                "error": None,
            }

        provider.fetch_report_rc = report_rc_with_history
        service = ResearchSnapshotService(providers={"tushare": provider})
        monkeypatch.setattr(
            service, "_build_cn_earnings_module", lambda **kwargs: _structured_module()
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                reported={"metrics": {"pe_ratio": 20}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
            ),
        )

        payload = service.poll_snapshot(
            market="cn",
            symbols=["300827"],
            start_date="20260226",
            end_date="20260328",
        )

        item = payload["items"][0]
        assert item["report_rc"]["records"][0]["report_date"] == "20251105"
        assert item["meta"]["modules"]["report_rc"]["notes"]["fallback_mode"] == (
            "latest_stock_specific_report_date"
        )
        assert item["meta"]["modules"]["report_rc"]["notes"]["resolved_start_date"] == "20251105"
        assert item["meta"]["modules"]["research_report"]["notes"]["skip_reason"] == (
            "no_stock_specific_report_rc_in_requested_window"
        )

    def test_us_base_default_modules(self, monkeypatch):
        monkeypatch.setattr(
            YfinanceDataSource,
            "get_us_financial_data",
            lambda symbol: (
                {"raw_data": {"info": {"longName": "NVIDIA"}}},
                {
                    "info": {
                        "longName": "NVIDIA",
                        "quoteType": "EQUITY",
                        "exchange": "NMS",
                        "currency": "USD",
                        "sector": "Technology",
                        "industry": "Semiconductors",
                    }
                },
            ),
        )
        service = ResearchSnapshotService(providers={"tushare": FakeResearchProvider()})
        monkeypatch.setattr(
            service,
            "_build_us_earnings_module",
            lambda **kwargs: _structured_module(
                reported={"quarter": "Q4"},
                consensus={"eps": {"estimate": 1.0}},
                derived={"growth": {"revenue_yoy": 0.25}, "coverage": {"analyst_count": 40}},
                source="yfinance",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_dcf_module",
            lambda **kwargs: _structured_module(
                reported={"assumptions": {"wacc": 0.09}},
                model_output={"equity_value_per_share": 120.5},
                source="yfinance",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_comps_module",
            lambda **kwargs: _structured_module(
                reported={"peer_set": [{"symbol": "AMD"}]},
                derived={"valuation_background": {"median_pe_ratio": 32.1}},
                source="yfinance",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_three_statement_module",
            lambda **kwargs: _structured_module(
                reported={"historical": {"revenue": [1, 2, 3]}},
                model_output={"scenario": "base"},
                source="yfinance",
            ),
        )
        monkeypatch.setattr(
            service,
            "_build_screen_module",
            lambda **kwargs: _structured_module(
                reported={"metrics": {"market_cap": 1000, "_source": "yfinance"}},
                derived={"filters": {}, "passed": True, "filter_count": 0},
                source="yfinance",
            ),
        )

        payload = service.poll_snapshot(market="us", symbols=["nvda"])

        assert payload["status"] == "ok"
        assert payload["request"]["mode"] == "base"
        item = payload["items"][0]
        assert item["status"] == "ok"
        assert item["info"]["common"]["name"] == "NVIDIA"
        assert item["info"]["us_specific"]["ts_code"] == "NVDA"
        assert set(item["meta"]["modules"].keys()) == {
            "earnings",
            "dcf",
            "comps",
            "three_statement",
            "screen",
        }
        assert item["dcf"]["model_output"]["equity_value_per_share"] == 120.5
        assert item["screen"]["metrics"]["market_cap"] == 1000
        assert item["summary"]["models"]["executed_modules"]["dcf"] == "ok"
        assert "derived" not in item

    def test_dcf_module_strips_subjective_fields(self, monkeypatch):
        service = ResearchSnapshotService(providers={"tushare": FakeResearchProvider()})

        class FakeResult:
            error = None

            def to_dict(self):
                return {}

        monkeypatch.setattr(DCFModel, "analyze", lambda self, symbol: FakeResult())
        monkeypatch.setattr(
            research_snapshot_module,
            "dcf_contract",
            lambda payload: {
                "entity": {"symbol": "NVDA"},
                "facts": {"reported": {}, "consensus": {}, "confidence": "high"},
                "analysis": {
                    "recommendation": "buy",
                    "derived": {"price_target": 100},
                },
                "meta": {
                    "schema_version": "2.0.0",
                    "interface_type": "model",
                    "sources": ["test"],
                    "data_completeness": "ok",
                    "limitations": [],
                    "as_of": None,
                },
            },
        )

        module = service._build_dcf_module(symbol="NVDA", options={})

        assert module["module_status"] == "ok"
        _assert_no_subjective_keys(module)


class TestResearchSnapshotCli:
    def test_cli_outputs_json_and_passes_mode(self):
        writer = StringIO()
        service = FakeSnapshotService()

        payload = research_snapshot_cli_main(
            [
                "--market",
                "cn",
                "--symbols",
                "600519,600519",
                "--mode",
                "full",
                "--pretty",
            ],
            writer=writer,
            service=service,
        )

        rendered = writer.getvalue()
        parsed = json.loads(rendered)
        assert payload["status"] == "ok"
        assert parsed["request"]["symbols"] == ["600519"]
        assert parsed["request"]["mode"] == "full"
        assert service.calls[0]["symbols"] == ["600519"]
        assert service.calls[0]["mode"] == "full"
