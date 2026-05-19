from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from datetime import date, datetime
import html as html_parser
import json
import os
import re
from typing import Any, Callable, Iterable
import urllib.parse

import requests

SOURCE = "hkipo_heat_scan"
USER_AGENT = (
    "Mozilla/5.0 (compatible; stock-analysis-api/1.0; +https://github.com/RyanProMax)"
)
DEFAULT_FETCH_TIMEOUT_SECONDS = 12.0
DEFAULT_MAX_WORKERS = 10
SOURCE_FAMILIES = (
    "futu_niuniu",
    "official_document",
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


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    parsed = _safe_float(value)
    return parsed if parsed is not None and parsed > 0 else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"(?i)</(?:td|th|tr|p|div|li|h[1-6])>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_parser.unescape(text)).strip()


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
    evidence["confidence"] = max(
        0.0, min(1.0, confidence if confidence is not None else 0.0)
    )
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
        item["structure_evidence"] = _normalize_auxiliary_evidence(
            item.get("structure_evidence"), report_date
        )
        item["valuation_evidence"] = _normalize_auxiliary_evidence(
            item.get("valuation_evidence"), report_date
        )
        item["structure_status"] = _classify_structure_status(
            item["structure_evidence"]
        )
        item["valuation_status"] = _classify_valuation_status(
            item["valuation_evidence"]
        )
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
            item.setdefault(
                "evidence_quality", "high" if len(usable) >= 2 else "medium"
            )
            item["subscription_heat"] = {
                **(
                    item.get("subscription_heat")
                    if isinstance(item.get("subscription_heat"), dict)
                    else {}
                ),
                **_score_subscription_heat(usable),
            }
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
                "score": 0,
                "score_status": "not_scorable",
                "usable_evidence_count": 0,
            }
        normalized_rows.append(item)

    normalized["data"] = normalized_rows
    summary = (
        normalized.get("summary") if isinstance(normalized.get("summary"), dict) else {}
    )
    normalized["summary"] = {
        "ipo_count": len(normalized_rows),
        "same_day_heat_count": same_day_count,
        "degraded_count": degraded_count,
        **summary,
    }
    return normalized


def _score_subscription_heat(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    multiples = [
        float(entry["value"])
        for entry in evidence
        if entry.get("field") in {"margin_multiple", "subscription_multiple"}
        and _safe_float(entry.get("value")) is not None
    ]
    best_multiple = max(multiples) if multiples else None
    if best_multiple is None:
        score = 4
    elif best_multiple >= 100:
        score = 20
    elif best_multiple >= 50:
        score = 17
    elif best_multiple >= 20:
        score = 14
    elif best_multiple >= 10:
        score = 10
    else:
        score = 6
    return {
        "status": "same_day_verified",
        "score": score,
        "score_status": "scored",
        "max_multiple": best_multiple,
        "usable_evidence_count": len(evidence),
        "source_family_count": len(
            {
                entry.get("source_family")
                for entry in evidence
                if entry.get("source_family")
            }
        ),
        "fields": sorted(
            {str(entry.get("field")) for entry in evidence if entry.get("field")}
        ),
    }


def _normalize_auxiliary_evidence(value: Any, report_date: str) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    return [
        normalize_heat_evidence(entry, report_date)
        for entry in rows
        if isinstance(entry, dict)
    ]


def _attributed_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in evidence
        if entry.get("staleness_status") != "invalid_missing_attribution"
        and _safe_float(entry.get("confidence")) is not None
        and float(entry.get("confidence", 0)) >= 0.5
    ]


def _classify_structure_status(evidence: list[dict[str, Any]]) -> str:
    fields = {str(entry.get("field")) for entry in _attributed_evidence(evidence)}
    if {
        "greenshoe_pct",
        "cornerstone_investor_count",
        "cornerstone_offer_pct",
        "sponsor",
    }.issubset(fields):
        return "core_structure_verified"
    if fields:
        return "partial_structure_verified"
    return "core_structure_not_verified"


def _classify_valuation_status(evidence: list[dict[str, Any]]) -> str:
    fields = {str(entry.get("field")) for entry in _attributed_evidence(evidence)}
    if {"core_capability", "industry", "peer_pe"}.issubset(fields) and (
        "fair_value_market_cap_range" in fields or "fair_value_price_range" in fields
    ):
        return "valuation_context_verified"
    if fields:
        return "partial_valuation_verified"
    return "valuation_context_not_verified"


@dataclass(frozen=True)
class SourceCandidate:
    source: str
    source_family: str
    url: str
    live_snapshot: bool = False


class HkIpoHeatScanService:
    def __init__(
        self,
        fetcher: Callable[[str], str] | None = None,
        *,
        fetch_timeout_seconds: float | None = None,
        max_workers: int | None = None,
    ):
        self.fetch_timeout_seconds = float(
            fetch_timeout_seconds
            if fetch_timeout_seconds is not None
            else _env_float(
                "HKIPO_HEAT_SCAN_FETCH_TIMEOUT_SECONDS",
                DEFAULT_FETCH_TIMEOUT_SECONDS,
            )
        )
        self.max_workers = int(
            max_workers
            if max_workers is not None
            else _env_int("HKIPO_HEAT_SCAN_MAX_WORKERS", DEFAULT_MAX_WORKERS)
        )
        self.fetcher = fetcher or self._default_fetch

    def _default_fetch(self, url: str) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.6",
        }
        response = requests.get(
            url,
            headers=headers,
            timeout=self.fetch_timeout_seconds,
        )
        response.raise_for_status()
        raw = response.content[:2_000_000]
        for encoding in [
            getattr(response, "encoding", None),
            getattr(response, "apparent_encoding", None),
            "utf-8",
            "big5",
            "gb18030",
        ]:
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
        name = _safe_str(
            ipo.get("display_name")
            or ipo.get("name_zh")
            or ipo.get("cn_name")
            or ipo.get("stock_name")
            or ipo.get("name")
        )
        name_en = _safe_str(
            ipo.get("name_en") or ipo.get("english_name") or ipo.get("name")
        )
        candidates = self._source_candidates(code=code, name=name, name_en=name_en)
        evidence: list[dict[str, Any]] = []
        structure_evidence: list[dict[str, Any]] = []
        valuation_evidence: list[dict[str, Any]] = []
        source_errors: list[dict[str, Any]] = []

        worker_count = max(1, min(self.max_workers, len(candidates)))
        evidence_by_index: list[list[dict[str, Any]]] = [[] for _ in candidates]
        structure_by_index: list[list[dict[str, Any]]] = [[] for _ in candidates]
        valuation_by_index: list[list[dict[str, Any]]] = [[] for _ in candidates]
        errors_by_index: list[list[dict[str, Any]]] = [[] for _ in candidates]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count
        ) as executor:
            futures = {
                executor.submit(self.fetcher, candidate.url): (index, candidate)
                for index, candidate in enumerate(candidates)
            }
            completed = concurrent.futures.as_completed(futures)
            for future in completed:
                index, candidate = futures[future]
                try:
                    html = future.result()
                    extracted = self._extract_page_evidence(
                        html,
                        candidate=candidate,
                        report_date=report_date,
                        code=code,
                        name=name,
                    )
                    evidence_by_index[index].extend(extracted["evidence"])
                    structure_by_index[index].extend(extracted["structure_evidence"])
                    valuation_by_index[index].extend(extracted["valuation_evidence"])
                except Exception as exc:  # pragma: no cover - network fallback only
                    errors_by_index[index].append(
                        {
                            "source": candidate.source,
                            "source_family": candidate.source_family,
                            "url": candidate.url,
                            "error": str(exc),
                        }
                    )
        for rows in evidence_by_index:
            evidence.extend(rows)
        for rows in structure_by_index:
            structure_evidence.extend(rows)
        for rows in valuation_by_index:
            valuation_evidence.extend(rows)
        for rows in errors_by_index:
            source_errors.extend(rows)
        return {
            "code": code,
            "name": name,
            "name_en": name_en,
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
            "structure_evidence": structure_evidence,
            "valuation_evidence": valuation_evidence,
            "source_errors": source_errors,
        }

    def _source_candidates(
        self, *, code: str, name: str, name_en: str = ""
    ) -> list[SourceCandidate]:
        raw_query = " ".join(
            part for part in [code.replace("HK.", ""), name, name_en, "孖展"] if part
        )
        query = urllib.parse.quote(raw_query)
        compact_code_value = code.replace("HK.", "")
        symbol = compact_code_value.lstrip("0") or compact_code_value
        compact_code = urllib.parse.quote(compact_code_value)
        quoted_name = urllib.parse.quote(name)
        return [
            SourceCandidate(
                "HKEXnews",
                "official_document",
                f"https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockId={compact_code}",
            ),
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
                "TradeSmart IPO Tracker",
                "multi_broker_aggregate",
                "https://www.lowrisktradesmart.org/zh/tools/ipo-tracker",
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
                "致富证券 IPO",
                "broker_margin_table",
                f"https://www.chiefgroup.com.hk/cn/securities/hk-ipo-detail/dp?symbol={symbol}",
                live_snapshot=True,
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

    def _make_evidence(
        self,
        *,
        candidate: SourceCandidate,
        report_date: str,
        source_time: str | None,
        field: str,
        value: Any,
        unit: str,
        confidence: float,
        source_time_field: str = "published_at",
        source_time_mode: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        evidence = {
            "source": candidate.source,
            "source_family": candidate.source_family,
            "field": field,
            "value": value,
            "unit": unit,
            "url": candidate.url,
            "confidence": confidence,
            **extra,
        }
        if source_time:
            evidence[source_time_field] = source_time
            evidence["staleness_status"] = classify_staleness(source_time, report_date)
        if source_time_mode:
            evidence["source_time_mode"] = source_time_mode
        return evidence

    def _extract_page_evidence(
        self,
        html: str,
        *,
        candidate: SourceCandidate,
        report_date: str,
        code: str = "",
        name: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        if candidate.source == "TradeSmart IPO Tracker":
            return {
                "evidence": list(
                    self._extract_tradesmart_margin_evidence(
                        html,
                        candidate=candidate,
                        report_date=report_date,
                        code=code,
                        name=name,
                    )
                ),
                "structure_evidence": [],
                "valuation_evidence": [],
            }

        text = _html_to_text(html)
        source_time, source_time_field, source_time_mode = self._extract_source_time(
            text, report_date, candidate=candidate
        )
        return {
            "evidence": list(
                self._extract_heat_evidence(
                    text,
                    candidate=candidate,
                    report_date=report_date,
                    source_time=source_time,
                    source_time_field=source_time_field,
                    source_time_mode=source_time_mode,
                )
            ),
            "structure_evidence": list(
                self._extract_structure_evidence(
                    text,
                    candidate=candidate,
                    report_date=report_date,
                    source_time=source_time,
                    source_time_field=source_time_field,
                    source_time_mode=source_time_mode,
                )
            ),
            "valuation_evidence": list(
                self._extract_valuation_evidence(
                    text,
                    candidate=candidate,
                    report_date=report_date,
                    source_time=source_time,
                    source_time_field=source_time_field,
                    source_time_mode=source_time_mode,
                )
            ),
        }

    def _extract_heat_evidence(
        self,
        text: str,
        *,
        candidate: SourceCandidate,
        report_date: str,
        source_time: str | None,
        source_time_field: str,
        source_time_mode: str | None,
    ) -> Iterable[dict[str, Any]]:
        patterns = [
            (
                "margin_multiple",
                r"(?:孖展|融资)(?:倍数|认购)?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:倍|x)?",
            ),
            (
                "subscription_multiple",
                r"(?:公开认购|认购)(?:倍数)?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:倍|x)?",
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
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=source_time,
                source_time_field=source_time_field,
                source_time_mode=source_time_mode,
                field=field,
                value=value,
                unit=(
                    "%" if field in {"grey_change_pct", "one_lot_success_rate"} else "x"
                ),
                confidence=0.55,
            )

    def _extract_tradesmart_margin_evidence(
        self,
        html: str,
        *,
        candidate: SourceCandidate,
        report_date: str,
        code: str,
        name: str,
    ) -> Iterable[dict[str, Any]]:
        compact_code = code.replace("HK.", "")
        if not compact_code:
            return

        record = self._find_tradesmart_margin_record(
            html, compact_code=compact_code, name=name
        )
        if record is None:
            return

        observed_at = record.get("observed_at")
        upstream_url = record.get("source_url")
        extra = {
            "upstream_source": "AiPO (myiqdii.com)",
            "upstream_url": upstream_url,
        }
        broker_top_text = record.get("broker_top_text")
        if broker_top_text:
            extra["top_broker"] = broker_top_text

        margin_multiple = _safe_float(record.get("oversubscription_ratio"))
        if margin_multiple is not None:
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=observed_at,
                source_time_field="updated_at",
                field="margin_multiple",
                value=margin_multiple,
                unit="x",
                confidence=0.62,
                **extra,
            )

        margin_total = _safe_float(record.get("margin_total_hkd_yi"))
        if margin_total is not None:
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=observed_at,
                source_time_field="updated_at",
                field="margin_amount_hkd_yi",
                value=margin_total,
                unit="HKD_yi",
                confidence=0.58,
                **extra,
            )

    def _find_tradesmart_margin_record(
        self, html: str, *, compact_code: str, name: str
    ) -> dict[str, Any] | None:
        margin_section_start = html.find(r"\"margin\"")
        search_space = (
            html[margin_section_start:] if margin_section_start >= 0 else html
        )
        record_pattern = re.compile(
            r"\{\\\"symbol\\\":\\\"(?P<symbol>\d{5})\\\"(?P<body>.*?)(?=\},\{\\\"symbol\\\"|\}\]\})",
            flags=re.DOTALL,
        )
        for match in record_pattern.finditer(search_space):
            if match.group("symbol") != compact_code:
                continue
            raw_record = match.group(0)
            if r"margin_total_hkd_yi" not in raw_record:
                continue
            record = {
                "symbol": match.group("symbol"),
                "name": self._extract_tradesmart_string(raw_record, "name"),
                "broker_top_text": self._extract_tradesmart_string(
                    raw_record, "broker_top_text"
                ),
                "observed_at": self._extract_tradesmart_string(
                    raw_record, "observed_at"
                ),
                "source_url": self._extract_tradesmart_string(raw_record, "source_url"),
                "margin_total_hkd_yi": self._extract_tradesmart_float(
                    raw_record, "margin_total_hkd_yi"
                ),
                "oversubscription_ratio": self._extract_tradesmart_float(
                    raw_record, "oversubscription_ratio"
                ),
            }
            if (
                name
                and record["name"]
                and not self._names_likely_match(name, str(record["name"]))
            ):
                continue
            return record
        return None

    def _extract_tradesmart_string(self, raw_record: str, key: str) -> str | None:
        match = re.search(
            rf"\\\"{re.escape(key)}\\\":\\\"(.*?)(?=\\\",\\\"|\\\"$)",
            raw_record,
        )
        if not match:
            return None
        try:
            return str(json.loads(f'"{match.group(1)}"'))
        except json.JSONDecodeError:
            return match.group(1).replace(r"\u0026", "&")

    def _extract_tradesmart_float(self, raw_record: str, key: str) -> float | None:
        match = re.search(
            rf"\\\"{re.escape(key)}\\\":([0-9]+(?:\.[0-9]+)?)", raw_record
        )
        return _safe_float(match.group(1) if match else None)

    def _names_likely_match(self, left: str, right: str) -> bool:
        normalize = lambda value: re.sub(r"[\s\-－—·・]", "", value).lower()
        left_norm = normalize(left)
        right_norm = normalize(right)
        return bool(
            left_norm
            and right_norm
            and (left_norm in right_norm or right_norm in left_norm)
        )

    def _extract_structure_evidence(
        self,
        text: str,
        *,
        candidate: SourceCandidate,
        report_date: str,
        source_time: str | None,
        source_time_field: str,
        source_time_mode: str | None,
    ) -> Iterable[dict[str, Any]]:
        numeric_patterns = [
            (
                "greenshoe_pct",
                r"(?:绿鞋|超额配股权|over-allotment).{0,24}?([0-9]+(?:\.[0-9]+)?)\s*%",
                "%",
            ),
            (
                "cornerstone_investor_count",
                r"基石投资者.{0,12}?([0-9]+)\s*(?:名|家|位)",
                "count",
            ),
            (
                "cornerstone_offer_pct",
                r"基石.{0,24}?(?:占|比例).{0,12}?([0-9]+(?:\.[0-9]+)?)\s*%",
                "%",
            ),
            (
                "public_float_pct",
                r"(?:公开发售比例|公开发售|公众货比例).{0,18}?([0-9]+(?:\.[0-9]+)?)\s*%",
                "%",
            ),
            (
                "clawback_max_pct",
                r"(?:回拨后最高|最高回拨|回拨).{0,18}?([0-9]+(?:\.[0-9]+)?)\s*%",
                "%",
            ),
        ]
        for field, pattern, unit in numeric_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = _safe_float(match.group(1))
            if value is None:
                continue
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=source_time,
                source_time_field=source_time_field,
                source_time_mode=source_time_mode,
                field=field,
                value=value,
                unit=unit,
                confidence=(
                    0.65 if candidate.source_family == "official_document" else 0.58
                ),
            )

        text_patterns = [
            (
                "sponsor",
                r"(?:独家保荐人|联席保荐人|保荐人|Sponsor)\s*[:：]?\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·&、,，（）()\s-]{1,80})",
            ),
            (
                "stabilizing_manager",
                r"(?:稳定价格操作人|稳定价格经办人)\s*[:：]?\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·&、,，（）()\s-]{1,80})",
            ),
        ]
        for field, pattern in text_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = self._clean_label_value(match.group(1).strip())
            if not value:
                continue
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=source_time,
                source_time_field=source_time_field,
                source_time_mode=source_time_mode,
                field=field,
                value=value,
                unit="text",
                confidence=(
                    0.62 if candidate.source_family == "official_document" else 0.55
                ),
            )

    def _extract_valuation_evidence(
        self,
        text: str,
        *,
        candidate: SourceCandidate,
        report_date: str,
        source_time: str | None,
        source_time_field: str,
        source_time_mode: str | None,
    ) -> Iterable[dict[str, Any]]:
        text_patterns = [
            ("core_business", r"(?:主营业务|主要业务)\s*[:：]?\s*([^。；;，,]{2,50})"),
            ("core_capability", r"核心能力\s*[:：]?\s*([^。；;，,]{2,50})"),
            (
                "industry",
                r"(?:所属行业|行业分类|行业板块|所属板块)\s*[:：]?\s*([^。；;，,]{2,40})",
            ),
        ]
        for field, pattern in text_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip()
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=source_time,
                source_time_field=source_time_field,
                source_time_mode=source_time_mode,
                field=field,
                value=value,
                unit="text",
                confidence=0.58,
            )

        peer_contexts = re.finditer(
            r"(?:同类股票|可比公司|可比|同业|peer|comparable).{0,180}",
            text,
            flags=re.IGNORECASE,
        )
        for context_match in peer_contexts:
            context = context_match.group(0)
            for match in re.finditer(
                r"([A-Za-z0-9\u4e00-\u9fff]{2,16})\s*(?:PE|市盈率)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:倍|x)?",
                context,
                flags=re.IGNORECASE,
            ):
                peer = match.group(1).strip()
                value = _safe_float(match.group(2))
                if (
                    value is None
                    or value <= 0
                    or not re.search(r"[A-Za-z\u4e00-\u9fff]", peer)
                ):
                    continue
                yield self._make_evidence(
                    candidate=candidate,
                    report_date=report_date,
                    source_time=source_time,
                    source_time_field=source_time_field,
                    source_time_mode=source_time_mode,
                    field="peer_pe",
                    value=value,
                    unit="x",
                    confidence=0.6,
                    peer=peer,
                )

        cap_match = re.search(
            r"(?:发行市值|上市市值|发售市值|市价|估值)\s*[:：]?\s*((?:HK\$?\s*)?[0-9]+(?:\.[0-9]+)?\s*(?:亿|億|萬|万)?)",
            text,
            flags=re.IGNORECASE,
        )
        if cap_match:
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=source_time,
                source_time_field=source_time_field,
                source_time_mode=source_time_mode,
                field="offer_market_cap",
                value=cap_match.group(1).strip(),
                unit="text",
                confidence=0.58,
            )

        pe_match = re.search(
            r"(?:市盈率|PE)\s*[:：]?\s*(-?[0-9]+(?:\.[0-9]+)?)",
            text,
            flags=re.IGNORECASE,
        )
        if pe_match:
            value = _safe_float(pe_match.group(1))
            if value is not None:
                yield self._make_evidence(
                    candidate=candidate,
                    report_date=report_date,
                    source_time=source_time,
                    source_time_field=source_time_field,
                    source_time_mode=source_time_mode,
                    field="pe_ratio",
                    value=value,
                    unit="x",
                    confidence=0.58,
                )

        range_match = re.search(
            r"合理(?:估值|市值)?区间\s*[:：]?\s*(HK\$?\s*[0-9]+(?:\.[0-9]+)?\s*(?:亿|萬|万)?)\s*[-–—至到]+\s*(HK\$?\s*[0-9]+(?:\.[0-9]+)?\s*(?:亿|萬|万)?)",
            text,
            flags=re.IGNORECASE,
        )
        if range_match:
            yield self._make_evidence(
                candidate=candidate,
                report_date=report_date,
                source_time=source_time,
                source_time_field=source_time_field,
                source_time_mode=source_time_mode,
                field="fair_value_market_cap_range",
                value={
                    "low": range_match.group(1).strip(),
                    "high": range_match.group(2).strip(),
                },
                unit="range",
                confidence=0.55,
            )

    def _extract_source_time(
        self, text: str, report_date: str, *, candidate: SourceCandidate
    ) -> tuple[str | None, str, str | None]:
        normalized_report_date = report_date[:10]
        if candidate.live_snapshot and self._active_subscription_window_contains(
            text, normalized_report_date
        ):
            return normalized_report_date, "updated_at", "active_subscription_window"

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
                    return candidate, "published_at", None
        return None, "published_at", None

    def _active_subscription_window_contains(self, text: str, report_date: str) -> bool:
        patterns = [
            r"招股日期\s*(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\s*[-–—至到]+\s*(20\d{2})[-/](\d{1,2})[-/](\d{1,2})",
            r"招股日期\s*(20\d{2})年(\d{1,2})月(\d{1,2})日?\s*[-–—至到]+\s*(20\d{2})年(\d{1,2})月(\d{1,2})日?",
        ]
        try:
            report = date.fromisoformat(report_date)
        except ValueError:
            return False
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            groups = [int(part) for part in match.groups()]
            start = date(groups[0], groups[1], groups[2])
            end = date(groups[3], groups[4], groups[5])
            if start <= report <= end:
                return True
        return False

    def _clean_label_value(self, value: str) -> str:
        stop_labels = [
            "包销商",
            "账簿管理人",
            "全球协调",
            "招股价",
            "上市价",
            "每手股数",
            "全球发售",
            "公开发售",
            "国际发售",
            "招股日期",
            "上市日期",
            "入场费",
            "认购倍数",
            "市价",
            "市盈率",
            "一手中籤率",
            "一手中签率",
            "申请人数",
            "招股文件",
            "公司概况",
            "主要业务",
        ]
        pattern = "|".join(re.escape(label) for label in stop_labels)
        cleaned = re.split(rf"(?:[。；;]|\s+(?:{pattern}))", value, maxsplit=1)[0]
        return cleaned.strip(" ，,")
