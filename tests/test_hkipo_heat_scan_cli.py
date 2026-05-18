from __future__ import annotations

from io import StringIO
import json
import threading

from src.services.hkipo_heat_scan_cli import main as hkipo_heat_scan_main
from src.services.hkipo_heat_scan_service import HkIpoHeatScanService


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
        entry["staleness_status"] == "invalid_missing_attribution" for entry in item["evidence"]
    )


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
