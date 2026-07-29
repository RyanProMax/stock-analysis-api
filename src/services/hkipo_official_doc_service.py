from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
from contextlib import contextmanager
import html
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable
import urllib.parse
import urllib.request

from .hkipo_heat_scan_service import classify_staleness

SOURCE = "hkipo_official_docs"
USER_AGENT = "Mozilla/5.0 (compatible; stock-analysis-api/1.0; +https://github.com/RyanProMax)"
DEFAULT_FETCH_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_DOCUMENTS_PER_IPO = 6
DEFAULT_MAX_PDF_PAGES = 450
NEW_LISTING_PAGES = [
    (
        "HKEXnews New Listings Main Board",
        "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=zh-HK",
    ),
    (
        "HKEXnews New Listings GEM",
        "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/GEM?sc_lang=zh-HK",
    ),
]


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


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_html(raw: str) -> str:
    without_scripts = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", without_scripts)
    return _normalize_space(html.unescape(text))


def _decode_bytes(raw: bytes) -> str:
    for encoding in ["utf-8", "big5", "gb18030", "latin-1"]:
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


@contextmanager
def _suppress_native_output():
    """Silence native PDF libraries that write diagnostics directly to process fds."""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)
        os.close(devnull_fd)


@dataclass(frozen=True)
class FetchResult:
    body: bytes
    content_type: str
    final_url: str


@dataclass(frozen=True)
class DocumentLink:
    title: str
    url: str
    document_type: str
    published_at: str | None


class HkIpoOfficialDocService:
    def __init__(
        self,
        fetcher: Callable[[str], Any] | None = None,
        *,
        fetch_timeout_seconds: float | None = None,
        max_documents_per_ipo: int | None = None,
    ):
        self.fetch_timeout_seconds = float(
            fetch_timeout_seconds
            if fetch_timeout_seconds is not None
            else _env_float(
                "HKIPO_OFFICIAL_DOC_FETCH_TIMEOUT_SECONDS",
                DEFAULT_FETCH_TIMEOUT_SECONDS,
            )
        )
        self.max_documents_per_ipo = int(
            max_documents_per_ipo
            if max_documents_per_ipo is not None
            else _env_int(
                "HKIPO_OFFICIAL_DOC_MAX_DOCUMENTS_PER_IPO",
                DEFAULT_MAX_DOCUMENTS_PER_IPO,
            )
        )
        self.max_pdf_pages = _env_int("HKIPO_OFFICIAL_DOC_MAX_PDF_PAGES", DEFAULT_MAX_PDF_PAGES)
        self.fetcher = fetcher or self._default_fetch

    def _default_fetch(self, url: str) -> FetchResult:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/pdf,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.6",
            },
        )
        with urllib.request.urlopen(request, timeout=self.fetch_timeout_seconds) as response:
            raw = response.read(8_000_000)
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
        return FetchResult(body=raw, content_type=content_type, final_url=final_url)

    def scan(
        self,
        *,
        report_date: str,
        ipos: list[dict[str, Any]],
        include_closed: bool,
        cache_dir: str | None = None,
    ) -> dict[str, Any]:
        rows = [
            self._scan_one(report_date=report_date, ipo=ipo, cache_dir=cache_dir)
            for ipo in ipos
            if include_closed or ipo.get("is_subscribe_status") is not False
        ]
        parsed_count = sum(len(row.get("documents", [])) for row in rows)
        degraded_count = sum(1 for row in rows if row.get("status") != "official_docs_parsed")
        return {
            "status": "ok",
            "source": SOURCE,
            "report_date": report_date,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "ipo_count": len(rows),
                "parsed_document_count": parsed_count,
                "degraded_count": degraded_count,
            },
            "data": rows,
            "errors": [],
        }

    def _scan_one(
        self,
        *,
        report_date: str,
        ipo: dict[str, Any],
        cache_dir: str | None,
    ) -> dict[str, Any]:
        code = _safe_str(ipo.get("code"))
        name = _safe_str(
            ipo.get("display_name")
            or ipo.get("name_zh")
            or ipo.get("cn_name")
            or ipo.get("stock_name")
            or ipo.get("name")
        )
        stock_id = code.replace("HK.", "")
        search_url = (
            "https://www1.hkexnews.hk/search/titlesearch.xhtml?"
            f"lang=zh&market=SEHK&stockId={urllib.parse.quote(stock_id)}"
        )
        source_errors: list[dict[str, Any]] = []
        documents: list[dict[str, Any]] = []
        structure_evidence: list[dict[str, Any]] = []
        valuation_evidence: list[dict[str, Any]] = []

        try:
            search_result = self._coerce_fetch_result(self.fetcher(search_url), search_url)
            search_html = _decode_bytes(search_result.body)
            links = self._extract_document_links(search_html, base_url=search_url)
        except Exception as exc:
            links = []
            source_errors.append(self._source_error(search_url, exc))

        if not links:
            for source_name, listing_url in NEW_LISTING_PAGES:
                try:
                    listing_result = self._coerce_fetch_result(
                        self.fetcher(listing_url), listing_url
                    )
                    listing_html = _decode_bytes(listing_result.body)
                    links.extend(
                        self._extract_new_listing_links(
                            listing_html,
                            base_url=listing_url,
                            ipo_code=code,
                            ipo_name=name,
                        )
                    )
                except Exception as exc:
                    source_errors.append(self._source_error(listing_url, exc, source=source_name))

        links = self._dedupe_links(links)

        if not links and not source_errors:
            source_errors.append(
                {
                    "source": "HKEXnews",
                    "source_family": "official_document",
                    "url": search_url,
                    "error": "no matching official documents found",
                }
            )

        for link in links[: self.max_documents_per_ipo]:
            try:
                fetched = self._fetch_with_cache(link.url, cache_dir)
                text = self._extract_text(fetched)
                source_time = self._extract_source_time(text, link.published_at, report_date)
                digest = sha256(fetched.body).hexdigest()
                documents.append(
                    {
                        "title": link.title,
                        "document_type": link.document_type,
                        "published_at": source_time,
                        "url": link.url,
                        "sha256": digest,
                        "bytes": len(fetched.body),
                        "parsed_text_chars": len(text),
                    }
                )
                structure_evidence.extend(
                    self._extract_structure_evidence(
                        text,
                        report_date=report_date,
                        source_time=source_time,
                        url=link.url,
                    )
                )
                valuation_evidence.extend(
                    self._extract_valuation_evidence(
                        text,
                        report_date=report_date,
                        source_time=source_time,
                        url=link.url,
                    )
                )
            except Exception as exc:
                source_errors.append(self._source_error(link.url, exc))

        status = (
            "official_docs_parsed"
            if documents
            else ("official_docs_degraded" if source_errors else "official_docs_not_found")
        )
        return {
            "code": code,
            "name": name,
            "stage": ipo.get("stage"),
            "status": status,
            "query_plan": [{"source": "HKEXnews", "url": search_url}],
            "documents": documents,
            "structure_evidence": self._dedupe_evidence(structure_evidence),
            "valuation_evidence": self._dedupe_evidence(valuation_evidence),
            "source_errors": source_errors,
        }

    def _fetch_with_cache(self, url: str, cache_dir: str | None) -> FetchResult:
        if not cache_dir:
            return self._coerce_fetch_result(self.fetcher(url), url)

        cache_root = Path(cache_dir)
        cache_root.mkdir(parents=True, exist_ok=True)
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".bin"
        cache_path = cache_root / f"{sha256(url.encode('utf-8')).hexdigest()}{suffix}"
        meta_path = cache_path.with_suffix(cache_path.suffix + ".json")
        if cache_path.exists():
            content_type = ""
            final_url = url
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    content_type = _safe_str(meta.get("content_type"))
                    final_url = _safe_str(meta.get("final_url")) or url
                except Exception:
                    pass
            return FetchResult(
                body=cache_path.read_bytes(),
                content_type=content_type,
                final_url=final_url,
            )

        fetched = self._coerce_fetch_result(self.fetcher(url), url)
        cache_path.write_bytes(fetched.body)
        meta_path.write_text(
            json.dumps(
                {"content_type": fetched.content_type, "final_url": fetched.final_url},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return fetched

    def _coerce_fetch_result(self, value: Any, url: str) -> FetchResult:
        if isinstance(value, FetchResult):
            return value
        if isinstance(value, dict):
            body = value.get("body", b"")
            raw = body if isinstance(body, bytes) else _safe_str(body).encode("utf-8")
            return FetchResult(
                body=raw,
                content_type=_safe_str(value.get("content_type")),
                final_url=_safe_str(value.get("final_url")) or url,
            )
        if isinstance(value, bytes):
            return FetchResult(body=value, content_type="", final_url=url)
        return FetchResult(body=_safe_str(value).encode("utf-8"), content_type="", final_url=url)

    def _extract_text(self, fetched: FetchResult) -> str:
        is_pdf = (
            "pdf" in fetched.content_type.lower()
            or urllib.parse.urlparse(fetched.final_url).path.lower().endswith(".pdf")
            or fetched.body.startswith(b"%PDF")
        )
        if is_pdf:
            pdf_text = self._extract_pdf_text(fetched.body)
            if pdf_text:
                return _normalize_space(pdf_text)
        raw = _decode_bytes(fetched.body)
        if "<" in raw and ">" in raw:
            return _strip_html(raw)
        return _normalize_space(raw)

    def _extract_pdf_text(self, raw: bytes) -> str:
        try:
            import fitz  # type: ignore

            with (
                _suppress_native_output(),
                fitz.open(stream=raw, filetype="pdf") as doc,
            ):
                page_count = min(doc.page_count, self.max_pdf_pages)
                text = "\n".join(
                    doc.load_page(index).get_text("text") for index in range(page_count)
                )
                if self._looks_like_useful_text(text):
                    return text
        except Exception:
            pass

        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(BytesIO(raw))
            pages = reader.pages[: self.max_pdf_pages]
            text = "\n".join(page.extract_text() or "" for page in pages)
            if self._looks_like_useful_text(text):
                return text
        except Exception:
            pass
        return _decode_bytes(raw)

    def _looks_like_useful_text(self, text: str) -> bool:
        normalized = _normalize_space(text)
        if len(normalized) < 100:
            return False
        return len(re.findall(r"[\u4e00-\u9fff]", normalized)) >= 20

    def _extract_document_links(self, text: str, *, base_url: str) -> list[DocumentLink]:
        links: list[DocumentLink] = []
        seen: set[str] = set()
        for match in re.finditer(
            r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            href = html.unescape(match.group(1))
            title = _strip_html(match.group(2)) or href
            document_type = self._classify_document_type(title)
            if document_type == "other":
                continue
            url = urllib.parse.urljoin(base_url, href)
            if url in seen:
                continue
            seen.add(url)
            links.append(
                DocumentLink(
                    title=title,
                    url=url,
                    document_type=document_type,
                    published_at=self._published_date_from_url(url),
                )
            )
        return links

    def _extract_new_listing_links(
        self,
        text: str,
        *,
        base_url: str,
        ipo_code: str,
        ipo_name: str,
    ) -> list[DocumentLink]:
        code_digits = re.sub(r"\D+", "", ipo_code)
        code_variants = {
            code_digits,
            code_digits.lstrip("0"),
            code_digits.zfill(4),
            code_digits.zfill(5),
        }
        code_variants.discard("")
        compact_name = re.sub(r"\s+", "", ipo_name)
        links: list[DocumentLink] = []

        for row_match in re.finditer(
            r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.IGNORECASE | re.DOTALL
        ):
            row_html = row_match.group(1)
            cells = [
                cell.group(1)
                for cell in re.finditer(
                    r"<td\b[^>]*>(.*?)</td>",
                    row_html,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            ]
            if len(cells) < 4:
                continue
            row_text = _strip_html(row_html)
            compact_row_text = re.sub(r"\s+", "", row_text)
            code_match = any(
                re.search(rf"(?<!\d){re.escape(variant)}(?!\d)", row_text)
                for variant in code_variants
            )
            name_match = bool(compact_name and compact_name in compact_row_text)
            if not code_match and not name_match:
                continue

            column_types = [
                (2, "listing_announcement", "新上市公告"),
                (3, "prospectus", "招股章程"),
                (4, "allotment_result", "股份配發結果"),
            ]
            for index, document_type, title in column_types:
                if index >= len(cells):
                    continue
                for href in self._extract_hrefs(cells[index]):
                    url = urllib.parse.urljoin(base_url, href)
                    links.append(
                        DocumentLink(
                            title=title,
                            url=url,
                            document_type=document_type,
                            published_at=self._published_date_from_url(url),
                        )
                    )
        return links

    def _extract_hrefs(self, html_text: str) -> list[str]:
        hrefs: list[str] = []
        for match in re.finditer(
            r"<a\b[^>]*?href=[\"']([^\"']+)[\"']",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            href = html.unescape(match.group(1)).strip()
            if href and not href.lower().startswith("javascript:"):
                hrefs.append(href)
        return hrefs

    def _dedupe_links(self, links: list[DocumentLink]) -> list[DocumentLink]:
        result: list[DocumentLink] = []
        seen: set[str] = set()
        for link in links:
            if link.url in seen:
                continue
            seen.add(link.url)
            result.append(link)
        return result

    def _dedupe_evidence(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (
                _safe_str(item.get("field")),
                json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _classify_document_type(self, title: str) -> str:
        lowered = title.lower()
        if (
            any(token in title for token in ["招股", "全球发售", "全球發售"])
            or "prospectus" in lowered
        ):
            return "prospectus"
        if (
            any(token in title for token in ["配发", "配發", "分配结果", "中签", "中籤"])
            or "allotment" in lowered
        ):
            return "allotment_result"
        if "稳定价格" in title or "穩定價格" in title or "stabil" in lowered:
            return "stabilization"
        if (
            any(token in title for token in ["定价", "定價", "发售价", "發售價"])
            or "offer price" in lowered
        ):
            return "pricing"
        return "other"

    def _published_date_from_url(self, url: str) -> str | None:
        match = re.search(r"/(20\d{2})/(\d{2})(\d{2})/", url)
        if not match:
            return None
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"

    def _extract_source_time(self, text: str, fallback: str | None, report_date: str) -> str | None:
        if fallback:
            return fallback

        normalized_report_date = report_date[:10]
        for pattern in [
            r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?",
            r"(\d{1,2})月(\d{1,2})日",
        ]:
            for match in re.finditer(pattern, text):
                groups = match.groups()
                if len(groups) == 3:
                    year, month, day = groups
                    candidate = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
                else:
                    month, day = groups
                    candidate = (
                        f"{int(normalized_report_date[:4]):04d}-{int(month):02d}-{int(day):02d}"
                    )
                try:
                    date.fromisoformat(candidate)
                    return candidate
                except ValueError:
                    continue
        return fallback

    def _make_evidence(
        self,
        *,
        url: str,
        report_date: str,
        source_time: str | None,
        field: str,
        value: Any,
        unit: str,
        confidence: float,
        snippet: str,
    ) -> dict[str, Any]:
        evidence = {
            "source": "HKEXnews",
            "source_family": "official_document",
            "field": field,
            "value": value,
            "unit": unit,
            "url": url,
            "confidence": confidence,
            "snippet": snippet[:180],
        }
        if source_time:
            evidence["published_at"] = source_time
            evidence["staleness_status"] = classify_staleness(source_time, report_date)
        else:
            evidence["staleness_status"] = "invalid_missing_attribution"
            evidence["missing_fields"] = ["published_at/update_at"]
        return evidence

    def _extract_structure_evidence(
        self,
        text: str,
        *,
        report_date: str,
        source_time: str | None,
        url: str,
    ) -> Iterable[dict[str, Any]]:
        greenshoe = self._extract_greenshoe_pct(text)
        if greenshoe:
            value, snippet = greenshoe
            yield self._make_evidence(
                url=url,
                report_date=report_date,
                source_time=source_time,
                field="greenshoe_pct",
                value=value,
                unit="%",
                confidence=0.92,
                snippet=snippet,
            )

        numeric_patterns = [
            (
                "cornerstone_investor_count",
                r"(?:基石投资者|基石投資者).{0,20}?([0-9]+)\s*(?:名|家|位)",
                "count",
            ),
            (
                "cornerstone_offer_pct",
                r"基石.{0,50}?(?:占|佔|比例|认购|認購).{0,20}?([0-9]+(?:\.[0-9]+)?)\s*%",
                "%",
            ),
            (
                "public_float_pct",
                r"(?:公开发售比例|公開發售比例|公众货比例|公眾貨比例|香港公开发售|香港公開發售)"
                r".{0,80}?(?:占|佔|比例|初步).{0,30}?([0-9]+(?:\.[0-9]+)?)\s*%",
                "%",
            ),
            (
                "clawback_max_pct",
                r"(?:回拨后最高|回撥後最高|最高回拨|最高回撥|回拨|回撥).{0,40}?([0-9]+(?:\.[0-9]+)?)\s*%",
                "%",
            ),
        ]
        for field, pattern, unit in numeric_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            snippet = match.group(0)
            if field == "cornerstone_offer_pct" and self._is_false_cornerstone_snippet(snippet):
                continue
            if field == "public_float_pct" and self._is_false_public_float_snippet(snippet):
                continue
            value = _safe_float(match.group(1))
            if value is None:
                continue
            yield self._make_evidence(
                url=url,
                report_date=report_date,
                source_time=source_time,
                field=field,
                value=value,
                unit=unit,
                confidence=0.9,
                snippet=snippet,
            )

        offer_share_match = re.search(
            r"全球發售的?發售股份數目[：:]?\s*([0-9,]+)\s*股H股.{0,80}?"
            r"香港發售股份數目[：:]?\s*([0-9,]+)\s*股H股",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if offer_share_match:
            total_shares = _safe_float(offer_share_match.group(1).replace(",", ""))
            public_shares = _safe_float(offer_share_match.group(2).replace(",", ""))
            if total_shares and public_shares:
                yield self._make_evidence(
                    url=url,
                    report_date=report_date,
                    source_time=source_time,
                    field="public_float_pct",
                    value=round(public_shares / total_shares * 100, 2),
                    unit="%",
                    confidence=0.9,
                    snippet=offer_share_match.group(0),
                )

        text_patterns = [
            (
                "sponsor",
                r"(?:独家保荐人|獨家保薦人|联席保荐人|聯席保薦人|保荐人|保薦人|Sponsor)\s*(?:为|為|是|[:：])\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·&、,，\s-]{1,60})",
            ),
            (
                "stabilizing_manager",
                r"(?:「(?:稳定价格操作人|穩定價格操作人|稳定价格经办人|穩定價格經辦人)」\s*指|(?:稳定价格操作人|穩定價格操作人|稳定价格经办人|穩定價格經辦人)\s*(?:为|為|是|[:：]))\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·&、,，\s-]{1,60})",
            ),
        ]
        for field, pattern in text_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = self._clean_role_value(match.group(1).strip())
            if not value or self._is_false_role_value(value):
                continue
            yield self._make_evidence(
                url=url,
                report_date=report_date,
                source_time=source_time,
                field=field,
                value=value,
                unit="text",
                confidence=0.88,
                snippet=match.group(0),
            )

    def _extract_greenshoe_pct(self, text: str) -> tuple[float, str] | None:
        patterns = [
            r"超額配股權[^。；;]{0,260}?不超過全球發售[^。；;]{0,80}?([0-9]+(?:\.[0-9]+)?)\s*%",
            r"超额配股权[^。；;]{0,260}?不超过全球发售[^。；;]{0,80}?([0-9]+(?:\.[0-9]+)?)\s*%",
            r"授予[^。；;]{0,50}?超額配股權[^。；;]{0,90}?(?:額外發行|不超過)[^。；;]{0,40}?([0-9]+(?:\.[0-9]+)?)\s*%",
            r"授予[^。；;]{0,50}?超额配股权[^。；;]{0,90}?(?:额外发行|不超过)[^。；;]{0,40}?([0-9]+(?:\.[0-9]+)?)\s*%",
            r"授予包銷商不超過[^。；;]{0,80}?([0-9]+(?:\.[0-9]+)?)\s*%[^。；;]{0,40}?超額配股權",
            r"授予包销商不超过[^。；;]{0,80}?([0-9]+(?:\.[0-9]+)?)\s*%[^。；;]{0,40}?超额配股权",
            r"可超額分配的股份數目[^。；;]{0,180}?佔全球發售[^。；;]{0,80}?約?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
            r"可超额分配的股份数目[^。；;]{0,180}?占全球发售[^。；;]{0,80}?约?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
            r"根據超額配股權可(?:出售|發行)[^。；;]{0,120}?佔全球發售[^。；;]{0,80}?約?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
            r"根据超额配股权可(?:出售|发行)[^。；;]{0,120}?占全球发售[^。；;]{0,80}?约?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                snippet = match.group(0)
                if self._is_false_greenshoe_snippet(snippet):
                    continue
                value = _safe_float(match.group(1))
                if value is not None:
                    return value, snippet
        return None

    def _is_false_greenshoe_snippet(self, snippet: str) -> bool:
        return any(
            token in snippet
            for token in [
                "經紀",
                "经纪",
                "佣金",
                "交易徵費",
                "交易征费",
                "會財局",
                "会财局",
                "聯交所交易費",
                "联交所交易费",
            ]
        )

    def _is_false_role_value(self, value: str) -> bool:
        normalized = value.strip()
        if normalized in {"收件人", "任何人士", "任何人士除外"}:
            return True
        return any(
            token in normalized
            for token in [
                "除外",
                "合理認為",
                "合理认为",
                "全權",
                "全权",
                "代其行事",
                "上市規則",
                "上市规则",
                "本公司",
            ]
        )

    def _clean_role_value(self, value: str) -> str:
        return re.split(
            r"(?:[。；;]|釋\s*義|释\s*义|附屬公司|附属公司|主要股東|主要股东|收購守則|收购守则)",
            value,
            maxsplit=1,
        )[0].strip(" ，,")

    def _is_false_cornerstone_snippet(self, snippet: str) -> bool:
        return any(
            token in snippet
            for token in [
                "生物科技公司10%",
                "指南",
                "上市規則",
                "上市规则",
                "現有股東",
                "现有股东",
            ]
        )

    def _is_false_public_float_snippet(self, snippet: str) -> bool:
        return any(
            token in snippet
            for token in [
                "超額配股權",
                "超额配股权",
                "30日",
                "最多",
                "穩定價格",
                "稳定价格",
            ]
        )

    def _extract_valuation_evidence(
        self,
        text: str,
        *,
        report_date: str,
        source_time: str | None,
        url: str,
    ) -> Iterable[dict[str, Any]]:
        text_patterns = [
            (
                "core_business",
                r"關於我們\s*(我們通過[^。；;]{2,220}。於往績記錄\s*期間[^。；;]{2,180})",
            ),
            (
                "core_business",
                r"(?:主要业务|主要業務|主营业务|主營業務)\s*[:：]\s*([^。；;]{2,120})",
            ),
            (
                "use_of_proceeds",
                r"(?:所得款项用途|所得款項用途|所得款项净额|所得款項淨額)\s+"
                r"(假設發售價[^。；;]{2,220})",
            ),
            (
                "use_of_proceeds",
                r"(?:所得款项用途|所得款項用途|所得款项净额|所得款項淨額)\s*[:：]?\s*([^。；;]{2,180})",
            ),
        ]
        for field, pattern in text_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip(" ，,")
            if value.count(".") > 8:
                continue
            yield self._make_evidence(
                url=url,
                report_date=report_date,
                source_time=source_time,
                field=field,
                value=value,
                unit="text",
                confidence=0.86,
                snippet=match.group(0),
            )

        cap_range_match = re.search(
            r"股份市值(?:\(\d+\))?.{0,80}?([0-9,]+(?:\.[0-9]+)?)\s*百萬港元"
            r"(?:\s+([0-9,]+(?:\.[0-9]+)?)\s*百萬港元)?",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if cap_range_match:
            low = cap_range_match.group(1).strip()
            high = cap_range_match.group(2)
            value = f"{low}-{high.strip()}百萬港元" if high else f"{low}百萬港元"
            yield self._make_evidence(
                url=url,
                report_date=report_date,
                source_time=source_time,
                field="offer_market_cap",
                value=value,
                unit="text",
                confidence=0.88,
                snippet=cap_range_match.group(0),
            )

        cap_match = re.search(
            r"(?:发行后市值|發行後市值|发行市值|發行市值|上市市值|市值).{0,16}?(HK\$?\s*[0-9]+(?:\.[0-9]+)?\s*(?:亿|億|萬|万)?)",
            text,
            flags=re.IGNORECASE,
        )
        if cap_match:
            yield self._make_evidence(
                url=url,
                report_date=report_date,
                source_time=source_time,
                field="offer_market_cap",
                value=cap_match.group(1).strip(),
                unit="text",
                confidence=0.86,
                snippet=cap_match.group(0),
            )

    def _source_error(
        self,
        url: str,
        exc: Exception,
        *,
        source: str = "HKEXnews",
    ) -> dict[str, Any]:
        return {
            "source": source,
            "source_family": "official_document",
            "url": url,
            "error": str(exc),
        }
