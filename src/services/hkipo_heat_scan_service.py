from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any, Callable, Iterable
import urllib.parse
import urllib.request

SOURCE = "hkipo_heat_scan"
USER_AGENT = "Mozilla/5.0 (compatible; stock-analysis-api/1.0; +https://github.com/RyanProMax)"
SOURCE_FAMILIES = (
    "futu_niuniu",
    "multi_broker_aggregate",
    "broker_margin_table",
    "finance_portal",
    "grey_market",
)
REQUIRED_EVIDENCE_KEYS = (
    "source",
    "source_family",
    "field",
    "value",
    "unit",
    "url",
    "confidence",
)


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _source_time(evidence: dict[str, Any]) -> str:
    return _safe_str(evidence.get("published_at") or evidence.get("updated_at"))


def classify_staleness(source_time: str, report_date: str) -> str:
    if not source_time:
        return "invalid_missing_attribution"
    try:
        parsed = datetime.fromisoformat(source_time)
        source_date = parsed.date()
    except ValueError:
        try:
            source_date = date.fromisoformat(source_time[:10])
        except ValueError:
            return "invalid_missing_attribution"
    return "same_day" if source_date.isoformat() == report_date else "stale"


def normalize_heat_evidence(raw: dict[str, Any], report_date: str) -> dict[str, Any]:
    evidence = dict(raw)
    for key in REQUIRED_EVIDENCE_KEYS:
        evidence.setdefault(key, None)
    if not evidence.get("published_at") and not evidence.get("updated_at"):
        evidence.setdefault("published_at", None)
    missing = [key for key in REQUIRED_EVIDENCE_KEYS if evidence.get(key) in (None, "")]
    if not _source_time(evidence):
        missing.append("published_at/update_at")
    if missing:
        evidence["staleness_status"] = "invalid_missing_attribution"
        evidence["missing_fields"] = sorted(set(missing))
        evidence.setdefault("confidence", 0)
        return evidence

    evidence["source"] = _safe_str(evidence.get("source"))
    evidence["source_family"] = _safe_str(evidence.get("source_family"))
    evidence["field"] = _safe_str(evidence.get("field"))
    evidence["unit"] = _safe_str(evidence.get("unit"))
    evidence["url"] = _safe_str(evidence.get("url"))
    confidence = _safe_float(evidence.get("confidence"))
    evidence["confidence"] = max(0.0, min(1.0, confidence if confidence is not None else 0.0))
    evidence["staleness_status"] = _safe_str(
        evidence.get("staleness_status")
    ) or classify_staleness(_source_time(evidence), report_date)
    return evidence


def normalize_scan_payload(payload: dict[str, Any], report_date: str) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("status", "ok")
    normalized.setdefault("source", SOURCE)
    normalized["report_date"] = report_date
    normalized.setdefault("errors", [])
    rows = normalized.get("data")
    data = rows if isinstance(rows, list) else []
    degraded_count = 0
    same_day_count = 0

    normalized_rows: list[dict[str, Any]] = []
    for row in data:
        item = dict(row) if isinstance(row, dict) else {"raw": row}
        raw_evidence = item.get("evidence")
        evidence_rows = raw_evidence if isinstance(raw_evidence, list) else []
        evidence = [
            normalize_heat_evidence(entry, report_date)
            for entry in evidence_rows
            if isinstance(entry, dict)
        ]
        item["evidence"] = evidence
        usable = [
            entry
            for entry in evidence
            if entry.get("staleness_status") == "same_day"
            and _safe_float(entry.get("confidence")) is not None
            and float(entry.get("confidence", 0)) >= 0.5
        ]
        if usable:
            same_day_count += 1
            item.setdefault("heat_status", "same_day_verified")
            item.setdefault("evidence_quality", "high" if len(usable) >= 2 else "medium")
            item.setdefault("subscription_heat", {"status": "usable"})
        else:
            degraded_count += 1
            item["heat_status"] = "heat_threshold_not_met"
            item["evidence_quality"] = "low"
            heat = (
                item.get("subscription_heat")
                if isinstance(item.get("subscription_heat"), dict)
                else {}
            )
            item["subscription_heat"] = {
                **heat,
                "status": "热度未达当日核验门槛",
            }
        normalized_rows.append(item)

    normalized["data"] = normalized_rows
    summary = normalized.get("summary") if isinstance(normalized.get("summary"), dict) else {}
    normalized["summary"] = {
        "ipo_count": len(normalized_rows),
        "same_day_heat_count": same_day_count,
        "degraded_count": degraded_count,
        **summary,
    }
    return normalized


@dataclass(frozen=True)
class SourceCandidate:
    source: str
    source_family: str
    url: str


class HkIpoHeatScanService:
    def __init__(self, fetcher: Callable[[str], str] | None = None):
        self.fetcher = fetcher or self._default_fetch

    def _default_fetch(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.6",
            },
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            content_type = response.headers.get_content_charset()
            raw = response.read(2_000_000)
        for encoding in [content_type, "utf-8", "big5", "gb18030"]:
            if not encoding:
                continue
            try:
                return raw.decode(encoding, errors="replace")
            except LookupError:
                continue
        return raw.decode("utf-8", errors="replace")

    def scan(
        self,
        *,
        report_date: str,
        ipos: list[dict[str, Any]],
        include_closed: bool,
    ) -> dict[str, Any]:
        data = [
            self._scan_one(report_date=report_date, ipo=ipo)
            for ipo in ipos
            if include_closed or ipo.get("is_subscribe_status") is not False
        ]
        return normalize_scan_payload(
            {
                "status": "ok",
                "source": SOURCE,
                "report_date": report_date,
                "summary": {"ipo_count": len(data)},
                "data": data,
                "errors": [],
            },
            report_date,
        )

    def _scan_one(self, *, report_date: str, ipo: dict[str, Any]) -> dict[str, Any]:
        code = _safe_str(ipo.get("code"))
        name = _safe_str(ipo.get("name"))
        candidates = self._source_candidates(code=code, name=name)
        evidence: list[dict[str, Any]] = []
        source_errors: list[dict[str, Any]] = []

        for candidate in candidates:
            try:
                html = self.fetcher(candidate.url)
                evidence.extend(
                    self._extract_evidence(
                        html,
                        candidate=candidate,
                        report_date=report_date,
                    )
                )
            except Exception as exc:  # pragma: no cover - network fallback only
                source_errors.append(
                    {
                        "source": candidate.source,
                        "source_family": candidate.source_family,
                        "url": candidate.url,
                        "error": str(exc),
                    }
                )

        return {
            "code": code,
            "name": name,
            "stage": ipo.get("stage"),
            "query_plan": [
                {
                    "source": candidate.source,
                    "source_family": candidate.source_family,
                    "url": candidate.url,
                }
                for candidate in candidates
            ],
            "evidence": evidence,
            "source_errors": source_errors,
        }

    def _source_candidates(self, *, code: str, name: str) -> list[SourceCandidate]:
        raw_query = " ".join(part for part in [code.replace("HK.", ""), name, "孖展"] if part)
        query = urllib.parse.quote(raw_query)
        compact_code_value = code.replace("HK.", "")
        compact_code = urllib.parse.quote(compact_code_value)
        quoted_name = urllib.parse.quote(name)
        return [
            SourceCandidate(
                "Futu/Niuniu",
                "futu_niuniu",
                f"https://www.futunn.com/stock/{compact_code_value}-HK",
            ),
            SourceCandidate(
                "AAStocks",
                "finance_portal",
                "https://www.aastocks.com/tc/stocks/market/ipo/mainpage.aspx",
            ),
            SourceCandidate(
                "ETNet",
                "finance_portal",
                f"https://www.etnet.com.hk/www/tc/stocks/ipo/search.php?keyword={query}",
            ),
            SourceCandidate(
                "TradeGo",
                "multi_broker_aggregate",
                f"https://www.tradego8.com/search?keyword={query}",
            ),
            SourceCandidate(
                "Zhitong",
                "finance_portal",
                f"https://www.zhitongcaijing.com/search?keyword={query}",
            ),
            SourceCandidate(
                "Sina HK",
                "finance_portal",
                f"https://search.sina.com.cn/?q={query}",
            ),
            SourceCandidate(
                "Gelonghui",
                "finance_portal",
                f"https://www.gelonghui.com/search?keyword={query}",
            ),
            SourceCandidate(
                "Phillip Securities IPO",
                "broker_margin_table",
                f"https://www.poems.com.hk/zh-hk/product-and-service/ipo/?keyword={quoted_name or compact_code}",
            ),
            SourceCandidate(
                "Tiger Brokers IPO",
                "broker_margin_table",
                f"https://www.itiger.com/hk/ipo?keyword={query}",
            ),
            SourceCandidate(
                "Valuable Capital IPO",
                "broker_margin_table",
                f"https://www.vbkr.com/ipo?keyword={query}",
            ),
        ]

    def _extract_evidence(
        self,
        html: str,
        *,
        candidate: SourceCandidate,
        report_date: str,
    ) -> Iterable[dict[str, Any]]:
        text = re.sub(r"\s+", " ", html)
        source_time = self._extract_source_time(text, report_date)
        patterns = [
            ("margin_multiple", r"(?:孖展|融资).{0,24}?([0-9]+(?:\.[0-9]+)?)\s*(?:倍|x)"),
            (
                "subscription_multiple",
                r"(?:公开认购|认购).{0,24}?([0-9]+(?:\.[0-9]+)?)\s*(?:倍|x)",
            ),
            (
                "one_lot_success_rate",
                r"(?:一手中签率|中签率).{0,24}?([0-9]+(?:\.[0-9]+)?)\s*%",
            ),
            ("grey_change_pct", r"(?:暗盘|灰市).{0,24}?([+-]?[0-9]+(?:\.[0-9]+)?)\s*%"),
        ]
        for field, pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = _safe_float(match.group(1))
            if value is None:
                continue
            evidence = {
                "source": candidate.source,
                "source_family": candidate.source_family,
                "field": field,
                "value": value,
                "unit": "%" if field in {"grey_change_pct", "one_lot_success_rate"} else "x",
                "url": candidate.url,
                "confidence": 0.55,
            }
            if source_time:
                evidence["published_at"] = source_time
                evidence["staleness_status"] = classify_staleness(source_time, report_date)
            yield evidence

    def _extract_source_time(self, text: str, report_date: str) -> str | None:
        normalized_report_date = report_date[:10]
        date_patterns = [
            r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?",
            r"(\d{1,2})月(\d{1,2})日",
        ]
        for pattern in date_patterns:
            for match in re.finditer(pattern, text):
                groups = match.groups()
                if len(groups) == 3:
                    year, month, day = groups
                    candidate = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
                else:
                    year = normalized_report_date[:4]
                    month, day = groups
                    candidate = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
                if candidate == normalized_report_date:
                    return candidate
        return None
