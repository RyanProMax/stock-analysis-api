from __future__ import annotations

from io import StringIO
import json

from src.services.hkipo_official_doc_cli import main as hkipo_official_doc_main
from src.services.hkipo_official_doc_service import HkIpoOfficialDocService


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


class FakeOfficialDocService:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def scan(
        self,
        *,
        report_date: str,
        ipos: list[dict],
        include_closed: bool,
        cache_dir: str | None,
    ) -> dict:
        self.calls.append(
            {
                "report_date": report_date,
                "ipos": ipos,
                "include_closed": include_closed,
                "cache_dir": cache_dir,
            }
        )
        return self.payload


def _run_cli(*args: str, service: FakeOfficialDocService) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = hkipo_official_doc_main(list(args), writer=writer, service=service)
    return exit_code, _strict_json_loads(writer.getvalue())


def test_hkipo_official_doc_cli_emits_structured_artifact(tmp_path):
    ipos_json = tmp_path / "ipos.json"
    cache_dir = tmp_path / "cache"
    ipos_json.write_text(
        json.dumps(
            [{"code": "HK.01234", "display_name": "示例智能", "stage": "subscription"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = FakeOfficialDocService(
        {
            "status": "ok",
            "source": "hkipo_official_docs",
            "report_date": "2026-05-17",
            "summary": {"ipo_count": 1, "parsed_document_count": 1},
            "data": [
                {
                    "code": "HK.01234",
                    "name": "示例智能",
                    "status": "official_docs_parsed",
                    "documents": [
                        {
                            "title": "招股章程",
                            "document_type": "prospectus",
                            "published_at": "2026-05-16",
                            "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0516/demo.pdf",
                        }
                    ],
                    "structure_evidence": [],
                    "valuation_evidence": [],
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
        "--cache-dir",
        str(cache_dir),
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
                    "display_name": "示例智能",
                    "stage": "subscription",
                }
            ],
            "include_closed": True,
            "cache_dir": str(cache_dir),
        }
    ]
    assert payload["source"] == "hkipo_official_docs"
    assert payload["summary"]["parsed_document_count"] == 1
    assert payload["data"][0]["documents"][0]["document_type"] == "prospectus"


def test_hkipo_official_doc_service_locates_and_parses_hkex_documents(tmp_path):
    search_url = (
        "https://www1.hkexnews.hk/search/titlesearch.xhtml?"
        "lang=zh&market=SEHK&stockId=01234"
    )
    prospectus_url = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0516/demo_prospectus.pdf"
    allotment_url = (
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0520/demo_allotment.pdf"
    )
    page = f"""
    <html><body>
      <a href="/listedco/listconews/sehk/2026/0516/demo_prospectus.pdf">招股章程</a>
      <a href="/listedco/listconews/sehk/2026/0520/demo_allotment.pdf">配发结果公告</a>
    </body></html>
    """
    prospectus_text = (
        "%PDF-1.4\n"
        "刊发日期：2026年5月16日 "
        "本公司已授予国际包销商超额配股权，可按发售价额外发行15%股份。 "
        "稳定价格操作人为中金公司。 "
        "基石投资者3名，认购发售股份约40%。 "
        "联席保荐人为摩根士丹利及中金公司。 "
        "香港公开发售初步占10%，回拨后最高50%。 "
        "按发售价计算，发行后市值约HK$100亿。 "
        "所得款项用途：研发、销售网络。 "
        "主要业务：AI营销平台。"
    ).encode("utf-8")
    allotment_text = "刊发日期：2026年5月20日 一手中签率 35% 公开认购 25.1倍"

    fetched_urls: list[str] = []

    def fetcher(url: str):
        fetched_urls.append(url)
        if url == search_url:
            return page
        if url == prospectus_url:
            return {"body": prospectus_text, "content_type": "application/pdf"}
        if url == allotment_url:
            return {"body": allotment_text, "content_type": "application/pdf"}
        raise AssertionError(f"unexpected url: {url}")

    service = HkIpoOfficialDocService(fetcher=fetcher)

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "display_name": "示例智能"}],
        include_closed=False,
        cache_dir=str(tmp_path),
    )

    item = payload["data"][0]
    docs_by_type = {doc["document_type"]: doc for doc in item["documents"]}
    structure_fields = {entry["field"] for entry in item["structure_evidence"]}
    valuation_fields = {entry["field"] for entry in item["valuation_evidence"]}
    assert item["status"] == "official_docs_parsed"
    assert {doc["document_type"] for doc in item["documents"]} == {
        "prospectus",
        "allotment_result",
    }
    assert docs_by_type["prospectus"]["published_at"] == "2026-05-16"
    assert {
        "greenshoe_pct",
        "stabilizing_manager",
        "cornerstone_investor_count",
        "cornerstone_offer_pct",
        "sponsor",
        "public_float_pct",
        "clawback_max_pct",
    }.issubset(structure_fields)
    assert {"offer_market_cap", "use_of_proceeds", "core_business"}.issubset(
        valuation_fields
    )
    assert item["source_errors"] == []
    assert payload["summary"]["parsed_document_count"] == 2

    service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.01234", "display_name": "示例智能"}],
        include_closed=False,
        cache_dir=str(tmp_path),
    )
    assert fetched_urls.count(prospectus_url) == 1
    assert fetched_urls.count(allotment_url) == 1


def test_hkipo_official_doc_service_falls_back_to_new_listing_table(tmp_path):
    title_search_url = (
        "https://www1.hkexnews.hk/search/titlesearch.xhtml?"
        "lang=zh&market=SEHK&stockId=02723"
    )
    main_board_url = "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=zh-HK"
    gem_url = "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/GEM?sc_lang=zh-HK"
    announcement_url = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0518/2026051800012_c.pdf"
    prospectus_url = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0518/2026051800024_c.pdf"
    main_board_page = f"""
    <table>
      <tr>
        <td>2723</td>
        <td>北京深演智能科技股份有限公司<br />DeepZero</td>
        <td><a href="{announcement_url}">下載</a></td>
        <td><a href="{prospectus_url}">下載</a></td>
        <td>&nbsp;</td>
      </tr>
    </table>
    """
    prospectus_text = (
        "刊发日期：2026年5月18日 "
        "全球發售的發售股份數目：9,068,000股H股 香港發售股份數目：906,800股H股。 "
        "本公司已授予国际包销商超额配股权，可按发售价额外发行15%股份。 "
        "基石投资者2名，认购发售股份约32%。 "
        "联席保荐人为中金公司。 "
        "主要业务：企业级AI营销平台。 "
        "按发售价计算，发行后市值约HK$88亿。 "
        "股份市值(1) 3,945百萬港元 5,033百萬港元。"
    )
    fetched_urls: list[str] = []

    def fetcher(url: str):
        fetched_urls.append(url)
        if url == title_search_url:
            return "<html><tbody></tbody></html>"
        if url == main_board_url:
            return main_board_page
        if url == gem_url:
            return "<table></table>"
        if url == announcement_url:
            return {
                "body": "刊发日期：2026年5月18日 新上市公告",
                "content_type": "text/html",
            }
        if url == prospectus_url:
            return {"body": prospectus_text, "content_type": "application/pdf"}
        raise AssertionError(f"unexpected url: {url}")

    service = HkIpoOfficialDocService(fetcher=fetcher)

    payload = service.scan(
        report_date="2026-05-18",
        ipos=[{"code": "HK.02723", "display_name": "北京深演智能科技股份有限公司"}],
        include_closed=False,
        cache_dir=str(tmp_path),
    )

    item = payload["data"][0]
    structure_fields = {entry["field"] for entry in item["structure_evidence"]}
    valuation_fields = {entry["field"] for entry in item["valuation_evidence"]}
    assert item["status"] == "official_docs_parsed"
    assert {doc["document_type"] for doc in item["documents"]} == {
        "listing_announcement",
        "prospectus",
    }
    assert {
        "greenshoe_pct",
        "cornerstone_investor_count",
        "sponsor",
        "public_float_pct",
    }.issubset(structure_fields)
    assert {"core_business", "offer_market_cap"}.issubset(valuation_fields)
    assert title_search_url in fetched_urls
    assert main_board_url in fetched_urls


def test_hkipo_official_doc_service_degrades_on_download_or_parse_failure(tmp_path):
    def fetcher(url: str):
        if "titlesearch" in url:
            return (
                '<a href="/listedco/listconews/sehk/2026/0516/broken.pdf">'
                "招股章程</a>"
            )
        raise TimeoutError("hkex download timed out")

    service = HkIpoOfficialDocService(fetcher=fetcher)

    payload = service.scan(
        report_date="2026-05-17",
        ipos=[{"code": "HK.05678", "display_name": "示例医疗"}],
        include_closed=False,
        cache_dir=str(tmp_path),
    )

    item = payload["data"][0]
    assert item["status"] == "official_docs_degraded"
    assert item["structure_evidence"] == []
    assert item["valuation_evidence"] == []
    assert item["source_errors"][0]["source"] == "HKEXnews"
    assert "hkex download timed out" in item["source_errors"][0]["error"]
