from __future__ import annotations

from io import StringIO
import json

from src.services.research_snapshot_cli import main as research_snapshot_cli_main
from src.services.research_snapshot_service import ResearchSnapshotService


def _rows_payload(rows=None, status="ok", error=None):
    return {"rows": rows or [], "status": status, "error": error}


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
            "computed_at": "2026-03-28T00:00:00+00:00",
            "source": "tushare",
            "market": kwargs["market"],
            "strategy": "tushare_first_research_snapshot_v1",
            "request": kwargs,
            "items": [],
        }


class TestResearchSnapshotService:
    def test_cn_snapshot_ok_with_derived_fields(self):
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

        payload = service.poll_snapshot(
            market="cn",
            symbols=["600519"],
            start_date="20260301",
            end_date="20260328",
        )

        assert payload["status"] == "ok"
        item = payload["items"][0]
        assert item["status"] == "ok"
        assert item["info"]["common"]["ts_code"] == "600519.SH"
        assert item["derived"]["coverage_snapshot"]["report_count"] == 1
        assert item["derived"]["estimate_snapshot"]["report_count"] == 1
        assert item["derived"]["change_flags"]["has_new_report_7d"] is True
        assert len(item["derived"]["catalyst_timeline"]) == 3

    def test_optional_permission_denied_marks_partial(self):
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
            news={
                "cls": _rows_payload([], status="permission_denied", error="权限不足"),
            },
        )
        service = ResearchSnapshotService(providers={"tushare": provider})

        payload = service.poll_snapshot(market="cn", symbols=["600519"])

        item = payload["items"][0]
        assert payload["status"] == "partial"
        assert item["status"] == "partial"
        assert item["news"]["source_meta"]["source_status"] == "permission_denied"

    def test_core_permission_denied_marks_failed(self):
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

        payload = service.poll_snapshot(market="cn", symbols=["600519"])

        item = payload["items"][0]
        assert item["status"] == "failed"
        assert item["error"]["code"] == "core_source_unavailable"

    def test_invalid_symbol_failed(self):
        service = ResearchSnapshotService(providers={"tushare": FakeResearchProvider()})

        payload = service.poll_snapshot(market="cn", symbols=["BAD"])

        assert payload["items"][0]["status"] == "failed"
        assert payload["items"][0]["error"]["code"] == "invalid_symbol"

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

        assert payload["items"][0]["status"] == "not_supported"

    def test_empty_core_results_return_zero_derived(self):
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
            anns_d=_rows_payload([], status="empty"),
        )
        service = ResearchSnapshotService(providers={"tushare": provider})

        payload = service.poll_snapshot(market="cn", symbols=["600519"])

        item = payload["items"][0]
        assert item["status"] == "ok"
        assert item["derived"]["coverage_snapshot"]["report_count"] == 0
        assert item["derived"]["estimate_snapshot"]["report_count"] == 0

    def test_news_filtering_and_exact_dedup(self):
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
            news={
                "cls": _rows_payload(
                    [
                        {
                            "datetime": "2026-03-24 09:30:00",
                            "title": "贵州茅台盘中走强",
                            "content": "贵州茅台 600519 今日高开。",
                            "src": "cls",
                        },
                        {
                            "datetime": "2026-03-24 09:30:00",
                            "title": "贵州茅台盘中走强",
                            "content": "贵州茅台 600519 今日高开。",
                            "src": "cls",
                        },
                        {
                            "datetime": "2026-03-24 11:00:00",
                            "title": "白酒板块异动",
                            "content": "板块整体活跃。",
                            "src": "cls",
                        },
                    ]
                )
            },
        )
        service = ResearchSnapshotService(providers={"tushare": provider})

        payload = service.poll_snapshot(market="cn", symbols=["600519"])

        news_items = payload["items"][0]["news"]["items"]
        assert len(news_items) == 1
        assert news_items[0]["title"] == "贵州茅台盘中走强"

    def test_report_rc_falls_back_to_latest_stock_specific_history_when_window_is_generic_only(
        self,
    ):
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

        history_calls = {"count": 0}

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
            history_calls["count"] += 1
            return {
                "rows": [
                    {
                        "report_date": "20251105",
                        "report_title": "上能电气：营收稳健增长",
                        "report_type": "点评",
                        "quarter": "2026Q4",
                        "org_name": "华安证券",
                    },
                    {
                        "report_date": "20251105",
                        "report_title": "上能电气：营收稳健增长",
                        "report_type": "点评",
                        "quarter": "2025Q4",
                        "org_name": "华安证券",
                    },
                ],
                "status": "ok",
                "error": None,
            }

        provider.fetch_report_rc = report_rc_with_history
        service = ResearchSnapshotService(providers={"tushare": provider})

        payload = service.poll_snapshot(
            market="cn",
            symbols=["300827"],
            start_date="20260226",
            end_date="20260328",
        )

        item = payload["items"][0]
        assert history_calls["count"] == 1
        assert item["report_rc"]["items"][0]["report_date"] == "20251105"
        assert (
            item["report_rc"]["source_meta"]["fallback_mode"] == "latest_stock_specific_report_date"
        )
        assert item["report_rc"]["source_meta"]["resolved_start_date"] == "20251105"
        assert (
            item["research_report"]["source_meta"]["skip_reason"]
            == "no_stock_specific_report_rc_in_requested_window"
        )

    def test_us_market_returns_not_implemented(self):
        service = ResearchSnapshotService(providers={"tushare": FakeResearchProvider()})

        payload = service.poll_snapshot(market="us", symbols=["NVDA"])

        assert payload["status"] == "not_implemented"
        assert payload["items"][0]["status"] == "not_implemented"


class TestResearchSnapshotCli:
    def test_cli_outputs_json_and_deduped_symbols(self):
        writer = StringIO()
        service = FakeSnapshotService()

        payload = research_snapshot_cli_main(
            ["--market", "cn", "--symbols", "600519,600519", "--pretty"],
            writer=writer,
            service=service,
        )

        rendered = writer.getvalue()
        parsed = json.loads(rendered)
        assert payload["status"] == "ok"
        assert parsed["request"]["symbols"] == ["600519"]
        assert service.calls[0]["symbols"] == ["600519"]
