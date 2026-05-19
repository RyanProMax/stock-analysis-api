from __future__ import annotations

from io import StringIO
import json
import threading

from src.services.hkipo_heat_scan_cli import main as hkipo_heat_scan_main
from src.services.hkipo_heat_scan_service import HkIpoHeatScanService
import src.services.hkipo_heat_scan_service as heat_scan_service


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


class FakeHkIpoHeatScanService:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def scan(self, *, report_date: str, ipos: list[dict], include_closed: bool) -> dict:
        self.calls.append(
            {
                "report_date": report_date,
                "ipos": ipos,
                "include_closed": include_closed,
            }
        )
        return self.payload


def _run_cli(*args: str, service: FakeHkIpoHeatScanService) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = hkipo_heat_scan_main(list(args), writer=writer, service=service)
    return exit_code, _strict_json_loads(writer.getvalue())


def test_hkipo_heat_scan_cli_emits_multisource_evidence_schema(tmp_path):
    ipos_json = tmp_path / "ipos.json"
    ipos_json.write_text(
        json.dumps(
            [
                {
                    "code": "HK.01234",
                    "name": "示例机器人",
                    "english_name": "Demo Robotics",
                    "stage": "subscription",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = FakeHkIpoHeatScanService(
        {
            "status": "ok",
            "source": "hkipo_heat_scan",
            "report_date": "2026-05-17",
            "summary": {"ipo_count": 1, "same_day_heat_count": 1, "degraded_count": 0},
            "data": [
                {
                    "code": "HK.01234",
                    "name": "示例机器人",
                    "heat_status": "same_day_verified",
                    "evidence_quality": "high",
                    "subscription_heat": {"score": 82, "status": "usable"},
                    "evidence": [
                        {
                            "source": "TradeGo",
                            "source_family": "multi_broker_aggregate",
                            "field": "margin_multiple",
                            "value": 128.5,
                            "unit": "x",
                            "published_at": "2026-05-17T12:30:00+08:00",
                            "url": "https://example.test/hkipo/HK.01234",
                            "confidence": 0.88,
                            "staleness_status": "same_day",
                        }
                    ],
                    "source_errors": [],
                }
            ],
            "errors": [],
        }
    )

    exit_code, payload = _run_cli(
        "--date",
        "2026-05-17",
        "--ipos-json",
        str(ipos_json),
        "--include-closed",
        "--json",
        service=service,
    )

    assert exit_code == 0
    assert service.calls == [
        {
            "report_date": "2026-05-17",
            "ipos": [
                {
                    "code": "HK.01234",
                    "name": "示例机器人",
                    "english_name": "Demo Robotics",
                    "stage": "subscription",
                }
            ],
            "include_closed": True,
        }
    ]
    evidence = payload["data"][0]["evidence"][0]
    assert payload["status"] == "ok"
    assert payload["source"] == "hkipo_heat_scan"
    assert payload["summary"]["same_day_heat_count"] == 1
    assert evidence == {
        "source": "TradeGo",
        "source_family": "multi_broker_aggregate",
        "field": "margin_multiple",
        "value": 128.5,
        "unit": "x",
        "published_at": "2026-05-17T12:30:00+08:00",
        "url": "https://example.test/hkipo/HK.01234",
        "confidence": 0.88,
        "staleness_status": "same_day",
    }


def test_hkipo_heat_scan_cli_normalizes_structure_and_valuation_evidence(tmp_path):
    ipos_json = tmp_path / "ipos.json"
    ipos_json.write_text(
        json.dumps([{"code": "HK.01234", "name": "示例智能"}], ensure_ascii=False),
        encoding="utf-8",
    )
    service = FakeHkIpoHeatScanService(
        {
            "status": "ok",
            "source": "hkipo_heat_scan",
            "report_date": "2026-05-17",
            "summary": {"ipo_count": 1},
            "data": [
                {
                    "code": "HK.01234",
                    "name": "示例智能",
                    "structure_evidence": [
                        {
                            "source": "HKEX",
                            "source_family": "official_document",
                            "field": "greenshoe_pct",
                            "value": 15,
                            "unit": "%",
                            "published_at": "2026-05-16",
                            "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0516/demo.pdf",
                            "confidence": 0.9,
                        }
                    ],
                    "valuation_evidence": [
                        {
                            "source": "AAStocks",
                            "source_family": "finance_portal",
                            "field": "peer_pe",
                            "value": 12.3,
                            "unit": "x",
                            "published_at": "2026-05-17",
                            "url": "https://example.test/ipo/valuation",
                            "confidence": 0.7,
                            "peer": "同业科技",
                        }
                    ],
                }
            ],
            "errors": [],
        }
    )

    exit_code, payload = _run_cli(
        "--date",
        "2026-05-17",
        "--ipos-json",
        str(ipos_json),
        "--json",
        service=service,
    )

    assert exit_code == 0
    item = payload["data"][0]
    assert item["structure_status"] == "partial_structure_verified"
    assert item["valuation_status"] == "partial_valuation_verified"
    assert item["structure_evidence"][0]["staleness_status"] == "stale"
    assert item["valuation_evidence"][0]["staleness_status"] == "same_day"
    assert item["valuation_evidence"][0]["peer"] == "同业科技"


def test_hkipo_heat_scan_cli_degrades_evidence_without_required_attribution(tmp_path):
    ipos_json = tmp_path / "ipos.json"
    ipos_json.write_text(
        json.dumps([{"code": "HK.05678", "name": "示例医疗"}], ensure_ascii=False),
        encoding="utf-8",
    )
    service = FakeHkIpoHeatScanService(
        {
            "status": "ok",
            "source": "hkipo_heat_scan",
            "report_date": "2026-05-17",
            "summary": {"ipo_count": 1},
            "data": [
                {
                    "code": "HK.05678",
                    "name": "示例医疗",
                    "heat_status": "same_day_verified",
                    "evidence_quality": "high",
                    "subscription_heat": {"score": 80, "status": "usable"},
                    "evidence": [
                        {
                            "source": "Unknown Forum",
                            "source_family": "finance_portal",
                            "field": "subscription_multiple",
                            "value": 12.1,
                            "unit": "x",
                        }
                    ],
                }
            ],
            "errors": [],
        }
    )

    exit_code, payload = _run_cli(
        "--date",
        "2026-05-17",
        "--ipos-json",
        str(ipos_json),
        "--json",
        service=service,
    )

    assert exit_code == 0
    item = payload["data"][0]
    assert item["heat_status"] == "heat_threshold_not_met"
    assert item["evidence_quality"] == "low"
    assert item["subscription_heat"]["status"] == "热度未达当日核验门槛"
    assert item["subscription_heat"]["score"] == 0
    assert item["subscription_heat"]["score_status"] == "not_scorable"
    assert item["evidence"][0]["staleness_status"] == "invalid_missing_attribution"


def test_hkipo_heat_scan_service_uses_same_day_source_time_for_main_heat():
    service = HkIpoHeatScanService(
        fetcher=lambda _url: "更新时间：2026年5月17日 孖展 128.5倍 公开认购 55.2倍"
    )

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "name": "示例机器人"}],
        include_closed=False,
    )

    item = payload["data"][0]
    assert item["heat_status"] == "same_day_verified"
    assert payload["summary"]["same_day_heat_count"] == 1
    assert any(entry["staleness_status"] == "same_day" for entry in item["evidence"])


def test_hkipo_heat_scan_service_degrades_scraped_value_without_source_time():
    service = HkIpoHeatScanService(fetcher=lambda _url: "孖展 128.5倍 公开认购 55.2倍")

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "name": "示例机器人"}],
        include_closed=False,
    )

    item = payload["data"][0]
    assert item["heat_status"] == "heat_threshold_not_met"
    assert item["subscription_heat"]["status"] == "热度未达当日核验门槛"
    assert all(
        entry["staleness_status"] == "invalid_missing_attribution"
        for entry in item["evidence"]
    )


def test_hkipo_heat_scan_service_extracts_chief_broker_detail_snapshot():
    def fetcher(url: str) -> str:
        if "chiefgroup.com.hk" not in url:
            return ""
        return """
        <h3>华曦达 (00901.HK)</h3>
        <table>
          <tr><td>股票编号</td><td>00901.HK</td></tr>
          <tr><td>股票名称</td><td>华曦达</td></tr>
          <tr><td>保荐人</td><td><span>中信建投(国际)融资有限公司</span><br /></td></tr>
          <tr><td>招股日期</td><td>2026-05-18 - 2026-05-21</td></tr>
          <tr><td>入场费</td><td>港元 3313.08</td></tr>
          <tr><td>认购倍数</td><td><span>14.2</span></td></tr>
          <tr><td>市价</td><td><span>68.73亿</span></td></tr>
          <tr><td>市盈率</td><td><span>26.01</span></td></tr>
          <tr><td>主要业务</td><td>公司是面向企业客户的智慧家庭解决方案提供商，致力推动AI技术在家庭空间场景的落地应用。</td></tr>
        </table>
        """

    service = HkIpoHeatScanService(fetcher=fetcher)

    payload = service.scan(
        report_date="2026-05-18",
        ipos=[{"code": "HK.00901", "display_name": "华曦达", "name": "SDMC"}],
        include_closed=False,
    )

    item = payload["data"][0]
    heat_fields = {entry["field"]: entry for entry in item["evidence"]}
    structure_fields = {entry["field"]: entry for entry in item["structure_evidence"]}
    valuation_fields = {entry["field"]: entry for entry in item["valuation_evidence"]}
    assert item["heat_status"] == "same_day_verified"
    assert item["subscription_heat"]["score"] > 0
    assert item["subscription_heat"]["score_status"] == "scored"
    assert heat_fields["subscription_multiple"]["value"] == 14.2
    assert heat_fields["subscription_multiple"]["source"] == "致富证券 IPO"
    assert heat_fields["subscription_multiple"]["updated_at"] == "2026-05-18"
    assert (
        heat_fields["subscription_multiple"]["source_time_mode"]
        == "active_subscription_window"
    )
    assert structure_fields["sponsor"]["value"] == "中信建投(国际)融资有限公司"
    assert valuation_fields["core_business"]["value"].startswith(
        "公司是面向企业客户的智慧家庭解决方案提供商"
    )
    assert valuation_fields["offer_market_cap"]["value"] == "68.73亿"
    assert valuation_fields["pe_ratio"]["value"] == 26.01


def test_hkipo_heat_scan_service_extracts_tradesmart_margin_pulse():
    html = r"""
    <script>
    self.__next_f.push([1,"15:[\"$\",\"$L16\",null,{\"locale\":\"zh\",\"data\":{\"margin\":{\"generated_at\":\"2026-05-19T02:02:05.223Z\",\"source\":\"AiPO (myiqdii.com)\",\"source_url\":\"https://aipo.myiqdii.com/trasaction/index\",\"records\":[{\"symbol\":\"02723\",\"symbol_hk\":\"02723.HK\",\"name\":\"深演智能\",\"margin_total_hkd_yi\":66.8769,\"oversubscription_ratio\":131.385,\"broker_top_text\":\"华泰国际: 1.4758亿\",\"observed_at\":\"2026-05-19T01:02:10.000Z\",\"scraped_at\":\"2026-05-19T01:05:43.724Z\",\"source_url\":\"https://aipo.myiqdii.com/Trasaction/MarginDetails?symbol=02723\u0026updateTime=2026/05/19%2009:02:10\"}]}}}]\n"])
    </script>
    """

    def fetcher(url: str) -> str:
        if "lowrisktradesmart.org" in url:
            return html
        return ""

    service = HkIpoHeatScanService(fetcher=fetcher)

    payload = service.scan(
        report_date="2026-05-19",
        ipos=[{"code": "HK.02723", "display_name": "深演智能"}],
        include_closed=False,
    )

    item = payload["data"][0]
    heat_fields = {entry["field"]: entry for entry in item["evidence"]}
    assert item["heat_status"] == "same_day_verified"
    assert item["subscription_heat"]["score"] == 20
    assert heat_fields["margin_multiple"]["value"] == 131.385
    assert heat_fields["margin_multiple"]["source"] == "TradeSmart IPO Tracker"
    assert heat_fields["margin_multiple"]["source_family"] == "multi_broker_aggregate"
    assert heat_fields["margin_multiple"]["updated_at"] == "2026-05-19T01:02:10.000Z"
    assert heat_fields["margin_multiple"]["staleness_status"] == "same_day"
    assert heat_fields["margin_multiple"]["upstream_source"] == "AiPO (myiqdii.com)"
    assert heat_fields["margin_amount_hkd_yi"]["value"] == 66.8769
    assert (
        "updateTime=2026/05/19%2009:02:10"
        in heat_fields["margin_multiple"]["upstream_url"]
    )


def test_hkipo_heat_scan_default_fetch_uses_requests_session(monkeypatch):
    calls: list[dict] = []

    class FakeResponse:
        content = "招股日期 2026-05-18 - 2026-05-21 认购倍数 14.2".encode()
        encoding = "utf-8"
        apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    def fake_get(url: str, *, headers: dict, timeout: float) -> FakeResponse:
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(heat_scan_service.requests, "get", fake_get)
    service = HkIpoHeatScanService(fetch_timeout_seconds=3.5)

    html = service._default_fetch("https://example.test/ipo")

    assert "认购倍数 14.2" in html
    assert calls == [
        {
            "url": "https://example.test/ipo",
            "headers": {
                "User-Agent": heat_scan_service.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.6",
            },
            "timeout": 3.5,
        }
    ]


def test_hkipo_heat_scan_service_prefers_display_name_for_query_plan():
    service = HkIpoHeatScanService(fetcher=lambda _url: "")

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[
            {
                "code": "HK.02723",
                "name": "DEEPZERO",
                "display_name": "深演智能",
                "name_en": "DEEPZERO",
            }
        ],
        include_closed=False,
    )

    item = payload["data"][0]
    query_urls = json.dumps(item["query_plan"], ensure_ascii=False)
    assert item["name"] == "深演智能"
    assert item["name_en"] == "DEEPZERO"
    assert (
        "深演智能" in query_urls or "%E6%B7%B1%E6%BC%94%E6%99%BA%E8%83%BD" in query_urls
    )
    assert "DEEPZERO" in query_urls


def test_hkipo_heat_scan_service_fetches_sources_concurrently():
    lock = threading.Lock()
    two_sources_started = threading.Event()
    started_urls: list[str] = []

    def fetcher(url: str) -> str:
        with lock:
            started_urls.append(url)
            if len(started_urls) >= 2:
                two_sources_started.set()
        if not two_sources_started.wait(0.5):
            raise AssertionError("source fetches did not overlap")
        return "更新时间：2026年5月17日 孖展 128.5倍 公开认购 55.2倍"

    service = HkIpoHeatScanService(fetcher=fetcher)

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "name": "示例机器人"}],
        include_closed=False,
    )

    item = payload["data"][0]
    assert len(started_urls) >= 2
    assert item["source_errors"] == []
    assert item["heat_status"] == "same_day_verified"


def test_hkipo_heat_scan_service_keeps_usable_evidence_when_one_source_fails():
    def fetcher(url: str) -> str:
        if "futunn.com" in url:
            raise TimeoutError("source timed out")
        return "更新时间：2026年5月17日 孖展 128.5倍 公开认购 55.2倍"

    service = HkIpoHeatScanService(fetcher=fetcher)

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "name": "示例机器人"}],
        include_closed=False,
    )

    item = payload["data"][0]
    assert item["heat_status"] == "same_day_verified"
    assert item["source_errors"] == [
        {
            "source": "Futu/Niuniu",
            "source_family": "futu_niuniu",
            "url": "https://www.futunn.com/stock/01234-HK",
            "error": "source timed out",
        }
    ]
    assert any(entry["field"] == "margin_multiple" for entry in item["evidence"])


def test_hkipo_heat_scan_service_extracts_structure_and_valuation_evidence():
    html = (
        "更新时间：2026年5月17日 "
        "孖展 128.5倍 公开认购 55.2倍 "
        "绿鞋 15% 超额配股权 基石投资者3名 基石占发售40% "
        "保荐人 高盛 稳定价格操作人 中金 公开发售比例 10% 回拨后最高 50% "
        "主营业务 AI营销平台 核心能力 数据智能投放 所属行业 SaaS营销科技 "
        "同类股票 商汤 PE 8.5倍 第四范式 PE 12.3倍 "
        "发行市值 HK$100亿 合理估值区间 HK$80亿-HK$120亿"
    )
    service = HkIpoHeatScanService(fetcher=lambda _url: html)

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "name": "示例智能"}],
        include_closed=False,
    )

    item = payload["data"][0]
    structure_fields = {entry["field"] for entry in item["structure_evidence"]}
    valuation_fields = {entry["field"] for entry in item["valuation_evidence"]}
    assert {
        "greenshoe_pct",
        "cornerstone_investor_count",
        "cornerstone_offer_pct",
        "sponsor",
        "stabilizing_manager",
        "public_float_pct",
        "clawback_max_pct",
    }.issubset(structure_fields)
    assert {
        "core_capability",
        "industry",
        "peer_pe",
        "offer_market_cap",
        "fair_value_market_cap_range",
    }.issubset(valuation_fields)
    assert item["structure_status"] == "core_structure_verified"
    assert item["valuation_status"] == "valuation_context_verified"


def test_hkipo_heat_scan_service_ignores_unqualified_peer_pe_fragments():
    html = (
        "更新时间：2026年5月17日 "
        "页面脚本 fragment PE 0x random PE 5x widget PE 57x "
        "主营业务 AI营销平台 核心能力 数据智能投放 行业 SaaS营销科技"
    )
    service = HkIpoHeatScanService(fetcher=lambda _url: html)

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "name": "示例智能"}],
        include_closed=False,
    )

    item = payload["data"][0]
    peer_pe_rows = [
        entry for entry in item["valuation_evidence"] if entry["field"] == "peer_pe"
    ]
    assert peer_pe_rows == []
