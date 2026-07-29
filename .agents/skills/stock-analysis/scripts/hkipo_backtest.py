#!/usr/bin/env python3
"""Backtest recent Hong Kong IPO first-day performance from public IPO tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote

AASTOCKS_LISTED_IPO_URL = "https://aastocks.com/en/stocks/market/ipo/listedipo.aspx"
XINGUYUFU_IPO_API_URL = "https://xinguyufu.cn/api/ipo"
USER_AGENT = "Mozilla/5.0 (compatible; stock-analysis-skill/1.0)"
FUTU_MARKET_DATA_SCRIPT = Path("scripts") / "futu_market_data.py"


@dataclass
class IpoSample:
    name: str
    code: str
    listing_date: str
    market_cap_text: str
    market_cap_mid_hkd_b: float | None
    industry: str
    offer_price: float | None
    listing_price: float | None
    oversub_rate: float | None
    applied_lots_for_one_lot: int | None
    one_lot_success_rate: float | None
    last_price: float | None
    debut_return_pct: float | None
    accumulated_return_pct: float | None
    heat_bucket: str
    valuation_bucket: str
    grey_market_return_pct: float | None
    greenshoe: str | None
    cornerstone: str | None
    heat_score: float | None
    industry_score: float | None
    valuation_score: float | None
    structure_score: float | None
    grey_score: float | None
    odds_score: int | None
    debut_return_source: str = "listed_table"
    listed_table_debut_return_pct: float | None = None
    futu_debut_close: float | None = None
    futu_debut_return_pct: float | None = None
    enrichment_source: str | None = None
    sponsor: str | None = None
    stabilizer: str | None = None
    clawback_pct: float | None = None
    futu_grey_market_return_pct: float | None = None


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table_stack = 0
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_stack += 1
            if self._table_stack == 1:
                self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            text = data.strip()
            if text:
                self._current_cell.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_cell is not None:
            self._current_row.append(" ".join(self._current_cell))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self._table_stack -= 1
            if self._table_stack == 0:
                self.tables.append(self._current_table)
                self._current_table = None


def fetch_url(url: str, timeout: int = 30, insecure_tls: bool = False) -> str:
    command = ["curl", "-L", "--max-time", str(timeout), "-A", USER_AGENT, "-sS"]
    if insecure_tls:
        command.append("-k")
    command.append(url)
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout + 5,
    )
    if completed.returncode != 0 and not completed.stdout:
        raise RuntimeError(completed.stderr.strip() or f"curl exit {completed.returncode}")
    return completed.stdout


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text or text.upper() == "N/A":
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def parse_int(value: str | None) -> int | None:
    number = parse_number(value)
    return int(number) if number is not None else None


def parse_pct(value: str | None) -> float | None:
    return parse_number(value)


def normalize_listing_date(value: str) -> str | None:
    match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", value)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def to_futu_hk_code(code: str) -> str:
    match = re.fullmatch(r"(\d{5})\.HK", code.strip())
    return f"HK.{match.group(1)}" if match else code.strip()


class NoopCloser:
    def close(self) -> None:
        return None


def _path_from_env_executable(value: str, env: dict[str, str] | None = None) -> Path | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    path_env = None if env is None else env.get("PATH", "")
    if os.sep not in raw_value and not (os.altsep and os.altsep in raw_value):
        resolved = shutil.which(raw_value, path=path_env)
        if resolved:
            return Path(resolved).expanduser().resolve()
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()
    return candidate if candidate.is_file() else None


def resolve_uv_path(
    uv_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    if uv_path:
        candidate = Path(uv_path).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        candidate = candidate.resolve()
        if candidate.is_file():
            return candidate

    resolved_env = os.environ if env is None else env
    for env_name in ("STOCK_ANALYSIS_UV", "UV_BIN", "UV"):
        candidate = _path_from_env_executable(resolved_env.get(env_name, ""), env=env)
        if candidate:
            return candidate
    path_uv = shutil.which("uv", path=None if env is None else resolved_env.get("PATH", ""))
    if path_uv:
        return Path(path_uv).expanduser().resolve()
    home_value = resolved_env.get("HOME") or str(Path.home())
    for candidate in (
        Path(home_value) / ".local" / "bin" / "uv",
        Path(home_value) / ".cargo" / "bin" / "uv",
    ):
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    return None


def resolve_futu_api_root(
    api_root: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    resolved_env = os.environ if env is None else env
    candidates: list[Path] = []
    if api_root:
        candidates.append(Path(api_root))
    env_root = resolved_env.get("STOCK_ANALYSIS_API_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    skill_root = Path(__file__).resolve().parents[1]
    ancestors = [skill_root, *list(skill_root.parents)[:4]]
    candidates.extend(ancestors)
    candidates.extend(ancestor / "stock-analysis-api" for ancestor in ancestors)
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / FUTU_MARKET_DATA_SCRIPT).is_file():
            return resolved
    return None


def last_json_line(output: str) -> str:
    stripped_output = str(output or "").strip()
    if stripped_output.startswith("{") and stripped_output.endswith("}"):
        return stripped_output
    for line in reversed(str(output or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
    return ""


def normalize_hk_numeric_code(code: str) -> str:
    match = re.search(r"(\d{5})", code.strip())
    return match.group(1) if match else code.strip()


def split_name_code(value: str) -> tuple[str, str]:
    match = re.search(r"(\d{5}\.HK)", value)
    if not match:
        return value.strip(), ""
    return value[: match.start()].strip(), match.group(1)


def parse_market_cap_mid(value: str | None) -> float | None:
    if value is None or value.strip().upper() == "N/A":
        return None
    numbers = [float(item.replace(",", "")) for item in re.findall(r"\d+(?:\.\d+)?", value)]
    if not numbers:
        return None
    if len(numbers) >= 2:
        return statistics.mean(numbers[:2])
    return numbers[0]


def classify_industry(name: str) -> str:
    upper = name.upper()
    rules = [
        ("biotech", ["-B", "BIO", "PHARM", "HEALTH", "MED", "DIAG", "VIGONVITA"]),
        ("semiconductor", ["SEMI", "GPIXEL", "FOURSEMI", "CHIP", "MICRO", "TIANYU"]),
        ("ai_tech", ["TECH", "ROBOT", "VISION", "DEEPEXI", "MANYCORE", "HAIZHI", "NSING"]),
        ("auto_ev", ["AUTO", "EV", "ZHIDA", "VOYAH", "BATTERY", "ENERGY"]),
        ("consumer", ["FOOD", "NOODLES", "POOLING", "TONGSHIFU", "GOLDEN LEAF", "BENQ"]),
        ("financial", ["FUTURES", "SECUR", "INSUR", "BANK"]),
    ]
    for industry, keywords in rules:
        if any(keyword in upper for keyword in keywords):
            return industry
    return "other"


def valuation_bucket(market_cap_mid_hkd_b: float | None) -> str:
    if market_cap_mid_hkd_b is None:
        return "unknown"
    if market_cap_mid_hkd_b < 2:
        return "<2B"
    if market_cap_mid_hkd_b < 10:
        return "2-10B"
    if market_cap_mid_hkd_b < 50:
        return "10-50B"
    return ">=50B"


def heat_score_from_rate(
    oversub_rate: float | None,
    one_lot_success_rate: float | None,
    applied_lots_for_one_lot: int | None,
) -> float | None:
    if oversub_rate is None:
        return None
    if oversub_rate < 10:
        score = 6
    elif oversub_rate < 50:
        score = 14
    elif oversub_rate < 200:
        score = 25
    elif oversub_rate < 1000:
        score = 35
    else:
        score = 45
    if one_lot_success_rate is not None:
        if one_lot_success_rate <= 1:
            score += 3
        elif one_lot_success_rate <= 5:
            score += 2
        elif one_lot_success_rate >= 30:
            score -= 3
    if applied_lots_for_one_lot is not None:
        if applied_lots_for_one_lot >= 3000:
            score += 3
        elif applied_lots_for_one_lot >= 1000:
            score += 2
        elif applied_lots_for_one_lot >= 300:
            score += 1
    return max(0, min(50, score))


def valuation_score_from_market_cap(market_cap_mid_hkd_b: float | None) -> float:
    if market_cap_mid_hkd_b is None:
        return 7.5
    if market_cap_mid_hkd_b < 2:
        return 11
    if market_cap_mid_hkd_b < 10:
        return 15
    if market_cap_mid_hkd_b < 50:
        return 10
    return 7


def structure_score_from_enrichment(greenshoe: str | None, cornerstone: str | None) -> float:
    score = 5.0
    green = (greenshoe or "").strip().lower()
    corner = (cornerstone or "").strip().lower()
    if green in {"yes", "y", "true", "1"}:
        score += 4
    elif green in {"no", "n", "false", "0"}:
        score -= 2
    if corner in {"yes", "y", "true", "1"}:
        score += 3
    elif corner in {"no", "n", "false", "0"}:
        score -= 1
    return max(0, min(10, score))


def grey_score_from_return(grey_market_return_pct: float | None) -> float:
    if grey_market_return_pct is None:
        return 5.0
    if grey_market_return_pct < 0:
        return 0
    if grey_market_return_pct < 20:
        return 5
    if grey_market_return_pct < 100:
        return 8
    if grey_market_return_pct < 250:
        return 9
    return 10


def load_enrichment(path: str | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    rows: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            code = (row.get("code") or "").strip()
            if code:
                rows[code] = row
    return rows


def get_enriched(row: dict[str, str], key: str) -> str | None:
    value = row.get(key)
    if value is None or value == "":
        return None
    return value


def heat_bucket(oversub_rate: float | None) -> str:
    if oversub_rate is None:
        return "unknown"
    if oversub_rate < 10:
        return "<10x"
    if oversub_rate < 50:
        return "10-50x"
    if oversub_rate < 200:
        return "50-200x"
    if oversub_rate < 1000:
        return "200-1000x"
    return ">=1000x"


def score_from_dimensions(
    heat_score: float | None,
    industry_score: float | None,
    valuation_score: float | None,
    structure_score: float | None,
    grey_score: float | None,
) -> int | None:
    if heat_score is None:
        return None
    score = heat_score
    score += industry_score if industry_score is not None else 10
    score += valuation_score if valuation_score is not None else 7.5
    score += structure_score if structure_score is not None else 7.5
    score += grey_score if grey_score is not None else 7.5
    return round(max(0, min(100, score)))


def make_futu_debut_close_fetcher(
    host: str = "127.0.0.1",
    port: int = 11111,
    *,
    api_root: str | Path | None = None,
    uv_path: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[Callable[[str, str], float | None], object]:
    resolved_api_root = resolve_futu_api_root(api_root=api_root, env=env)
    if not resolved_api_root:
        raise RuntimeError("未找到 stock-analysis-api Futu CLI（scripts/futu_market_data.py）")
    resolved_uv_path = resolve_uv_path(uv_path=uv_path, env=env)
    if not resolved_uv_path:
        raise RuntimeError("未找到 uv 可执行文件，无法运行 stock-analysis-api Futu CLI")

    process_env = dict(os.environ if env is None else env)
    process_env.setdefault("PYTHONIOENCODING", "utf-8")
    process_env["FUTU_OPEND_HOST"] = str(host)
    process_env["FUTU_OPEND_PORT"] = str(port)

    def fetch_close(code: str, listing_date: str) -> float | None:
        futu_code = to_futu_hk_code(code)
        proc = subprocess.run(
            [
                str(resolved_uv_path),
                "run",
                "python",
                str(FUTU_MARKET_DATA_SCRIPT),
                "kline",
                "--code",
                futu_code,
                "--ktype",
                "1d",
                "--start",
                listing_date,
                "--end",
                listing_date,
                "--num",
                "1",
                "--rehab",
                "none",
                "--json",
            ],
            cwd=str(resolved_api_root),
            env=process_env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            return None
        json_line = last_json_line(proc.stdout)
        if not json_line:
            return None
        try:
            payload = json.loads(json_line)
        except json.JSONDecodeError:
            return None
        if payload.get("status") == "failed" or payload.get("error"):
            return None
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        close = row.get("close") if isinstance(row, dict) else None
        return float(close) if close not in {None, ""} else None

    return fetch_close, NoopCloser()


def close_futu_context(ctx: object | None) -> None:
    if ctx is None:
        return
    close = getattr(ctx, "close", None)
    if callable(close):
        close()


def apply_futu_debut_returns(
    samples: list[IpoSample],
    fetch_close: Callable[[str, str], float | None] | None = None,
    delay: float = 0.55,
    host: str = "127.0.0.1",
    port: int = 11111,
    api_root: str | Path | None = None,
    uv_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    ctx = None
    if fetch_close is None:
        fetch_close, ctx = make_futu_debut_close_fetcher(
            host,
            port,
            api_root=api_root,
            uv_path=uv_path,
            env=env,
        )
    updated = 0
    try:
        for sample in samples:
            listing_date = normalize_listing_date(sample.listing_date)
            if listing_date is None or sample.offer_price is None or sample.offer_price <= 0:
                continue
            close = fetch_close(sample.code, listing_date)
            if close is None or close <= 0:
                continue
            if sample.listed_table_debut_return_pct is None:
                sample.listed_table_debut_return_pct = sample.debut_return_pct
            futu_return = (close - sample.offer_price) / sample.offer_price * 100
            sample.futu_debut_close = close
            sample.futu_debut_return_pct = futu_return
            sample.debut_return_pct = futu_return
            sample.debut_return_source = "futu_kline"
            updated += 1
            if delay > 0 and ctx is not None:
                time.sleep(delay)
    finally:
        close_futu_context(ctx)
    return updated


def parse_xinguyufu_bool(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in {"有", "yes", "Yes", "YES", "true", "True", "1"}:
        return "yes"
    if text in {"无", "no", "No", "NO", "false", "False", "0", "--", "-"}:
        return "no"
    return text


def fetch_xinguyufu_ipo_row(
    code: str, base_url: str = XINGUYUFU_IPO_API_URL, timeout: int = 30
) -> dict | None:
    numeric_code = normalize_hk_numeric_code(code)
    url = f"{base_url}?limit=30&stock={quote(numeric_code)}"
    payload = json.loads(fetch_url(url, timeout=timeout))
    rows = payload.get("data") or []
    for row in rows:
        if normalize_hk_numeric_code(str(row.get("代码", ""))) == numeric_code:
            return row
    return rows[0] if rows else None


def apply_xinguyufu_enrichment(
    samples: list[IpoSample],
    fetch_row: Callable[[str], dict | None] | None = None,
    delay: float = 0.1,
    base_url: str = XINGUYUFU_IPO_API_URL,
) -> int:
    if fetch_row is None:
        fetch_row = lambda code: fetch_xinguyufu_ipo_row(code, base_url=base_url)
    updated = 0
    for sample in samples:
        numeric_code = normalize_hk_numeric_code(sample.code)
        row = fetch_row(numeric_code)
        if not row:
            continue
        grey_market = row.get("暗盘涨幅_百分比")
        futu_grey = row.get("富途暗盘_百分比")
        greenshoe_pct = row.get("绿鞋公开_百分比")
        cornerstone = parse_xinguyufu_bool(row.get("基石"))
        sponsor = row.get("保荐人")
        stabilizer = row.get("稳价人")
        clawback = row.get("回拨比例_百分比")
        industry = row.get("行业")

        sample.enrichment_source = "xinguyufu"
        sample.grey_market_return_pct = (
            parse_number(str(grey_market))
            if grey_market is not None
            else sample.grey_market_return_pct
        )
        sample.futu_grey_market_return_pct = (
            parse_number(str(futu_grey))
            if futu_grey is not None
            else sample.futu_grey_market_return_pct
        )
        sample.clawback_pct = (
            parse_number(str(clawback)) if clawback is not None else sample.clawback_pct
        )
        if greenshoe_pct is not None:
            parsed_greenshoe_pct = parse_number(str(greenshoe_pct))
            sample.greenshoe = "yes" if parsed_greenshoe_pct and parsed_greenshoe_pct > 0 else "no"
        if cornerstone is not None:
            sample.cornerstone = cornerstone
        if sponsor not in {None, "", "--", "-"}:
            sample.sponsor = str(sponsor)
        if stabilizer not in {None, "", "--", "-"}:
            sample.stabilizer = str(stabilizer)
        if industry not in {None, "", "--", "-"}:
            sample.industry = str(industry)
        updated += 1
        if delay > 0 and fetch_row is not None:
            time.sleep(delay)
    return updated


def find_ipo_table(html: str) -> list[list[str]]:
    parser = TableParser()
    parser.feed(html)
    for table in parser.tables:
        flat = " ".join(" ".join(row) for row in table[:3])
        if "Over-sub" in flat and "Debut" in flat and "Listing Date" in flat:
            return table
    return []


def parse_samples_from_html(
    html: str, enrichment: dict[str, dict[str, str]] | None = None
) -> list[IpoSample]:
    table = find_ipo_table(html)
    enrichment = enrichment or {}
    samples: list[IpoSample] = []
    for row in table[1:]:
        if len(row) < 13 or not re.search(r"\d{5}\.HK", row[1]):
            continue
        name, code = split_name_code(row[1])
        extra = enrichment.get(code, {})
        oversub = parse_number(row[7])
        one_lot_success = parse_pct(row[9])
        market_cap_text = row[4]
        market_cap_mid = parse_market_cap_mid(market_cap_text)
        industry = get_enriched(extra, "industry") or classify_industry(name)
        grey_market_return = parse_pct(get_enriched(extra, "grey_market_return_pct"))
        greenshoe = get_enriched(extra, "greenshoe")
        cornerstone = get_enriched(extra, "cornerstone")
        heat_score = heat_score_from_rate(oversub, one_lot_success, parse_int(row[8]))
        valuation_score = valuation_score_from_market_cap(market_cap_mid)
        structure_score = structure_score_from_enrichment(greenshoe, cornerstone)
        grey_score = grey_score_from_return(grey_market_return)
        samples.append(
            IpoSample(
                name=name,
                code=code,
                listing_date=row[2],
                market_cap_text=market_cap_text,
                market_cap_mid_hkd_b=market_cap_mid,
                industry=industry,
                offer_price=parse_number(row[5]),
                listing_price=parse_number(row[6]),
                oversub_rate=oversub,
                applied_lots_for_one_lot=parse_int(row[8]),
                one_lot_success_rate=one_lot_success,
                last_price=parse_number(row[10]),
                debut_return_pct=parse_pct(row[11]),
                accumulated_return_pct=parse_pct(row[12]),
                heat_bucket=heat_bucket(oversub),
                valuation_bucket=valuation_bucket(market_cap_mid),
                grey_market_return_pct=grey_market_return,
                greenshoe=greenshoe,
                cornerstone=cornerstone,
                heat_score=heat_score,
                industry_score=None,
                valuation_score=valuation_score,
                structure_score=structure_score,
                grey_score=grey_score,
                odds_score=None,
            )
        )
    return samples


def load_aastocks_samples(
    limit: int, enrichment: dict[str, dict[str, str]] | None = None, delay: float = 0.2
) -> list[IpoSample]:
    samples: list[IpoSample] = []
    page = 1
    while len(samples) < limit:
        url = (
            AASTOCKS_LISTED_IPO_URL
            if page == 1
            else f"{AASTOCKS_LISTED_IPO_URL}?s=3&o=0&page={page}"
        )
        page_samples = parse_samples_from_html(fetch_url(url), enrichment)
        if not page_samples:
            break
        existing_codes = {sample.code for sample in samples}
        samples.extend(sample for sample in page_samples if sample.code not in existing_codes)
        page += 1
        if delay > 0:
            time.sleep(delay)
    return samples[:limit]


def mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return numerator / (denom_x * denom_y)


def ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        average_rank = (index + 1 + end) / 2
        for original_index, _ in indexed[index:end]:
            result[original_index] = average_rank
        index = end
    return result


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    return pearson(ranks(xs), ranks(ys))


def score_bucket(odds_score: int | None) -> str:
    if odds_score is None:
        return "unknown"
    if odds_score >= 90:
        return "90-100"
    if odds_score >= 80:
        return "80-89"
    if odds_score >= 65:
        return "65-79"
    if odds_score >= 50:
        return "50-64"
    return "<50"


def compact_mismatch_sample(sample: IpoSample, mismatch_type: str) -> dict:
    return {
        "type": mismatch_type,
        "code": sample.code,
        "name": sample.name,
        "industry": sample.industry,
        "odds_score": sample.odds_score,
        "listing_date": sample.listing_date,
        "heat_bucket": sample.heat_bucket,
        "oversub_rate": sample.oversub_rate,
        "one_lot_success_rate": sample.one_lot_success_rate,
        "debut_return_pct": sample.debut_return_pct,
    }


def summarize_score_calibration(samples: list[IpoSample]) -> dict:
    scored = [
        sample
        for sample in samples
        if sample.odds_score is not None and sample.debut_return_pct is not None
    ]
    by_score_bucket = []
    for bucket in ["90-100", "80-89", "65-79", "50-64", "<50", "unknown"]:
        bucket_samples = [sample for sample in scored if score_bucket(sample.odds_score) == bucket]
        bucket_returns = [
            sample.debut_return_pct
            for sample in bucket_samples
            if sample.debut_return_pct is not None
        ]
        if not bucket_samples:
            continue
        wins = [value for value in bucket_returns if value > 0]
        breaks = [value for value in bucket_returns if value < 0]
        by_score_bucket.append(
            {
                "bucket": bucket,
                "count": len(bucket_samples),
                "win_rate": len(wins) / len(bucket_returns) if bucket_returns else None,
                "avg_return_pct": mean(bucket_returns),
                "median_return_pct": median(bucket_returns),
                "break_rate": len(breaks) / len(bucket_returns) if bucket_returns else None,
            }
        )
    xs = [float(sample.odds_score) for sample in scored if sample.odds_score is not None]
    ys = [sample.debut_return_pct for sample in scored if sample.debut_return_pct is not None]
    by_score = sorted(scored, key=lambda item: item.odds_score or -1, reverse=True)
    edge_count = max(1, math.ceil(len(by_score) * 0.2)) if by_score else 0
    top_returns = [
        sample.debut_return_pct
        for sample in by_score[:edge_count]
        if sample.debut_return_pct is not None
    ]
    bottom_returns = [
        sample.debut_return_pct
        for sample in by_score[-edge_count:]
        if sample.debut_return_pct is not None
    ]
    high_score_breaks = [
        compact_mismatch_sample(sample, "高分破发")
        for sample in sorted(
            [
                item
                for item in scored
                if (item.odds_score or 0) >= 80 and (item.debut_return_pct or 0) < 0
            ],
            key=lambda item: (-(item.odds_score or 0), item.debut_return_pct or 0),
        )
    ]
    low_score_winners = [
        compact_mismatch_sample(sample, "低分大涨")
        for sample in sorted(
            [
                item
                for item in scored
                if (item.odds_score or 0) < 65 and (item.debut_return_pct or 0) >= 50
            ],
            key=lambda item: (-(item.debut_return_pct or 0), item.odds_score or 0),
        )
    ]
    top_median = median(top_returns)
    bottom_median = median(bottom_returns)
    return {
        "scored_count": len(scored),
        "by_score_bucket": by_score_bucket,
        "score_return_rank_correlation": spearman(xs, ys),
        "top_score_median_return_pct": top_median,
        "bottom_score_median_return_pct": bottom_median,
        "top_bottom_median_spread_pct": (
            top_median - bottom_median
            if top_median is not None and bottom_median is not None
            else None
        ),
        "mismatch_samples": (high_score_breaks + low_score_winners)[:10],
    }


def apply_industry_scores(samples: list[IpoSample]) -> None:
    valid = [sample for sample in samples if sample.debut_return_pct is not None]
    grouped: dict[str, list[float]] = {}
    for sample in valid:
        grouped.setdefault(sample.industry, []).append(sample.debut_return_pct or 0)
    industry_scores: dict[str, float] = {}
    for industry, returns in grouped.items():
        win_rate = len([value for value in returns if value > 0]) / len(returns)
        med = statistics.median(returns)
        score = 5 + win_rate * 6
        if med > 50:
            score += 4
        elif med > 20:
            score += 2
        elif med < 0:
            score -= 3
        industry_scores[industry] = max(0, min(15, score))
    for sample in samples:
        sample.industry_score = industry_scores.get(sample.industry, 10.0)
        sample.odds_score = score_from_dimensions(
            sample.heat_score,
            sample.industry_score,
            sample.valuation_score,
            sample.structure_score,
            sample.grey_score,
        )


def summarize(samples: list[IpoSample]) -> dict:
    apply_industry_scores(samples)
    valid = [sample for sample in samples if sample.debut_return_pct is not None]
    returns = [sample.debut_return_pct for sample in valid if sample.debut_return_pct is not None]
    scored = [sample for sample in valid if sample.odds_score is not None]
    by_bucket = []
    for bucket in ["<10x", "10-50x", "50-200x", "200-1000x", ">=1000x", "unknown"]:
        bucket_samples = [sample for sample in valid if sample.heat_bucket == bucket]
        bucket_returns = [
            sample.debut_return_pct
            for sample in bucket_samples
            if sample.debut_return_pct is not None
        ]
        if not bucket_samples:
            continue
        wins = [value for value in bucket_returns if value > 0]
        breaks = [value for value in bucket_returns if value < 0]
        by_bucket.append(
            {
                "bucket": bucket,
                "count": len(bucket_samples),
                "win_rate": len(wins) / len(bucket_returns) if bucket_returns else None,
                "avg_return_pct": mean(bucket_returns),
                "median_return_pct": median(bucket_returns),
                "break_rate": len(breaks) / len(bucket_returns) if bucket_returns else None,
            }
        )
    xs = [float(sample.odds_score) for sample in scored]
    ys = [sample.debut_return_pct for sample in scored if sample.debut_return_pct is not None]
    debut_return_source_counts: dict[str, int] = {}
    for sample in valid:
        source = sample.debut_return_source
        debut_return_source_counts[source] = debut_return_source_counts.get(source, 0) + 1
    enrichment_source_counts: dict[str, int] = {}
    for sample in samples:
        if sample.enrichment_source:
            source = sample.enrichment_source
            enrichment_source_counts[source] = enrichment_source_counts.get(source, 0) + 1
    by_industry = []
    for industry in sorted({sample.industry for sample in valid}):
        industry_returns = [
            sample.debut_return_pct
            for sample in valid
            if sample.industry == industry and sample.debut_return_pct is not None
        ]
        if industry_returns:
            by_industry.append(
                {
                    "industry": industry,
                    "count": len(industry_returns),
                    "win_rate": len([value for value in industry_returns if value > 0])
                    / len(industry_returns),
                    "median_return_pct": median(industry_returns),
                }
            )
    by_valuation = []
    for bucket in ["<2B", "2-10B", "10-50B", ">=50B", "unknown"]:
        bucket_returns = [
            sample.debut_return_pct
            for sample in valid
            if sample.valuation_bucket == bucket and sample.debut_return_pct is not None
        ]
        if bucket_returns:
            by_valuation.append(
                {
                    "bucket": bucket,
                    "count": len(bucket_returns),
                    "win_rate": len([value for value in bucket_returns if value > 0])
                    / len(bucket_returns),
                    "median_return_pct": median(bucket_returns),
                }
            )
    return {
        "sample_count": len(samples),
        "valid_debut_return_count": len(valid),
        "debut_return_source_counts": debut_return_source_counts,
        "enrichment_source_counts": enrichment_source_counts,
        "win_rate": (
            len([value for value in returns if value > 0]) / len(returns) if returns else None
        ),
        "avg_return_pct": mean(returns),
        "median_return_pct": median(returns),
        "break_rate": (
            len([value for value in returns if value < 0]) / len(returns) if returns else None
        ),
        "score_return_correlation": pearson(xs, ys),
        "score_calibration": summarize_score_calibration(scored),
        "enrichment_coverage": {
            "greenshoe": len([sample for sample in samples if sample.greenshoe is not None]),
            "cornerstone": len([sample for sample in samples if sample.cornerstone is not None]),
            "grey_market": len(
                [sample for sample in samples if sample.grey_market_return_pct is not None]
            ),
            "futu_grey_market": len(
                [sample for sample in samples if sample.futu_grey_market_return_pct is not None]
            ),
            "stabilizer": len([sample for sample in samples if sample.stabilizer is not None]),
            "sponsor": len([sample for sample in samples if sample.sponsor is not None]),
            "market_cap": len(
                [sample for sample in samples if sample.market_cap_mid_hkd_b is not None]
            ),
        },
        "by_heat_bucket": by_bucket,
        "by_industry": by_industry,
        "by_valuation": by_valuation,
        "top_debut_returns": [
            asdict(sample)
            for sample in sorted(
                valid, key=lambda item: item.debut_return_pct or -999, reverse=True
            )[:10]
        ],
        "worst_debut_returns": [
            asdict(sample)
            for sample in sorted(valid, key=lambda item: item.debut_return_pct or 999)[:10]
        ],
    }


def fmt_pct(value: float | None, digits: int = 1) -> str:
    return "N/A" if value is None else f"{value * 100:.{digits}f}%"


def fmt_num(value: float | None, digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def fmt_source_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "N/A"
    return "；".join(f"{source} {count}" for source, count in sorted(counts.items()))


def render_data_source_note(summary: dict) -> str:
    sources = summary.get("debut_return_source_counts", {})
    enrichment_sources = summary.get("enrichment_source_counts", {})
    enrichment_note = ""
    if enrichment_sources.get("xinguyufu"):
        enrichment_note = "新股渔夫公开 API 补充绿鞋、基石、暗盘、保荐人和稳价人字段。"
    if sources.get("futu_kline"):
        return f"数据源：AAStocks Listed IPO 页面提供样本清单、发行价、超购和一手中签率；Futu/OpenD 历史日 K 线提供首日收盘价并重算首日涨幅。{enrichment_note}"
    return f"数据源：AAStocks Listed IPO 页面；字段定义以页面备注为准。{enrichment_note}"


def render_markdown(summary: dict) -> str:
    lines = [
        "# 港股 IPO 首日回测",
        "",
        "## 总览",
        f"- 样本数：{summary['sample_count']}；有效首日涨幅样本：{summary['valid_debut_return_count']}",
        f"- 首日胜率：{fmt_pct(summary['win_rate'])}；破发率：{fmt_pct(summary['break_rate'])}",
        f"- 平均首日涨幅：{fmt_num(summary['avg_return_pct'])}%；中位首日涨幅：{fmt_num(summary['median_return_pct'])}%",
        f"- 首日涨幅来源：{fmt_source_counts(summary['debut_return_source_counts'])}",
        f"- 补充字段来源：{fmt_source_counts(summary['enrichment_source_counts'])}",
        f"- 多维评分与首日涨幅相关系数：{fmt_num(summary['score_return_correlation'], 3)}",
        f"- 评分排序相关系数：{fmt_num(summary['score_calibration']['score_return_rank_correlation'], 3)}；Top 20% 评分中位首日涨幅 {fmt_num(summary['score_calibration']['top_score_median_return_pct'])}%，Bottom 20% {fmt_num(summary['score_calibration']['bottom_score_median_return_pct'])}%，分差 {fmt_num(summary['score_calibration']['top_bottom_median_spread_pct'])}pct",
        f"- 字段覆盖：市值 {summary['enrichment_coverage']['market_cap']}/{summary['sample_count']}；绿鞋 {summary['enrichment_coverage']['greenshoe']}/{summary['sample_count']}；基石 {summary['enrichment_coverage']['cornerstone']}/{summary['sample_count']}；辉立暗盘 {summary['enrichment_coverage']['grey_market']}/{summary['sample_count']}；富途暗盘 {summary['enrichment_coverage']['futu_grey_market']}/{summary['sample_count']}；稳价人 {summary['enrichment_coverage']['stabilizer']}/{summary['sample_count']}",
        "",
        "## 融资/认购热度分桶",
        "| 热度分桶 | 样本数 | 胜率 | 平均首日涨幅 | 中位首日涨幅 | 破发率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for bucket in summary["by_heat_bucket"]:
        lines.append(
            "| {bucket} | {count} | {win_rate} | {avg} | {median} | {break_rate} |".format(
                bucket=bucket["bucket"],
                count=bucket["count"],
                win_rate=fmt_pct(bucket["win_rate"]),
                avg=fmt_num(bucket["avg_return_pct"]),
                median=fmt_num(bucket["median_return_pct"]),
                break_rate=fmt_pct(bucket["break_rate"]),
            )
        )
    lines += [
        "",
        "## 评分分桶校准",
        "| 评分分桶 | 样本数 | 胜率 | 平均首日涨幅 | 中位首日涨幅 | 破发率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for bucket in summary["score_calibration"]["by_score_bucket"]:
        lines.append(
            "| {bucket} | {count} | {win_rate} | {avg} | {median} | {break_rate} |".format(
                bucket=bucket["bucket"],
                count=bucket["count"],
                win_rate=fmt_pct(bucket["win_rate"]),
                avg=fmt_num(bucket["avg_return_pct"]),
                median=fmt_num(bucket["median_return_pct"]),
                break_rate=fmt_pct(bucket["break_rate"]),
            )
        )
    lines += ["", "## 行业分桶", "| 行业 | 样本数 | 胜率 | 中位首日涨幅 |", "|---|---:|---:|---:|"]
    for item in sorted(
        summary["by_industry"], key=lambda row: row["median_return_pct"] or -999, reverse=True
    ):
        lines.append(
            f"| {item['industry']} | {item['count']} | {fmt_pct(item['win_rate'])} | {fmt_num(item['median_return_pct'])}% |"
        )
    lines += [
        "",
        "## 估值/市值分桶",
        "| 市值分桶 | 样本数 | 胜率 | 中位首日涨幅 |",
        "|---|---:|---:|---:|",
    ]
    for item in summary["by_valuation"]:
        lines.append(
            f"| {item['bucket']} | {item['count']} | {fmt_pct(item['win_rate'])} | {fmt_num(item['median_return_pct'])}% |"
        )
    lines += [
        "",
        "## 评分失配样本",
        "| 类型 | 代码 | 公司 | 行业 | 评分 | 上市日 | 热度分桶 | 首日涨幅 |",
        "|---|---|---|---|---:|---|---|---:|",
    ]
    for sample in summary["score_calibration"]["mismatch_samples"]:
        lines.append(
            f"| {sample['type']} | {sample['code']} | {sample['name']} | {sample['industry']} | {sample['odds_score']} | {sample['listing_date']} | {sample['heat_bucket']} | {fmt_num(sample['debut_return_pct'])}% |"
        )
    if not summary["score_calibration"]["mismatch_samples"]:
        lines.append("| 无 | - | - | - | - | - | - | - |")
    lines += [
        "",
        "## Top 10 首日涨幅",
        "| 代码 | 公司 | 行业 | 评分 | 上市日 | 超购倍数 | 一手中签率 | 首日涨幅 |",
        "|---|---|---|---:|---|---:|---:|---:|",
    ]
    for sample in summary["top_debut_returns"]:
        lines.append(
            f"| {sample['code']} | {sample['name']} | {sample['industry']} | {sample['odds_score']} | {sample['listing_date']} | {fmt_num(sample['oversub_rate'], 1)}x | {fmt_num(sample['one_lot_success_rate'], 1)}% | {fmt_num(sample['debut_return_pct'])}% |"
        )
    lines += [
        "",
        "## Worst 10 首日涨幅",
        "| 代码 | 公司 | 行业 | 评分 | 上市日 | 超购倍数 | 一手中签率 | 首日涨幅 |",
        "|---|---|---|---:|---|---:|---:|---:|",
    ]
    for sample in summary["worst_debut_returns"]:
        lines.append(
            f"| {sample['code']} | {sample['name']} | {sample['industry']} | {sample['odds_score']} | {sample['listing_date']} | {fmt_num(sample['oversub_rate'], 1)}x | {fmt_num(sample['one_lot_success_rate'], 1)}% | {fmt_num(sample['debut_return_pct'])}% |"
        )
    lines += [
        "",
        "## 校准建议",
        "- 当前增强版自动纳入行业、市值/估值、绿鞋、基石和暗盘；字段来源可能是公开 API 或 enrichment CSV。",
        "- 当前评分校准仍是同源样本内评估；行业分使用样本分桶启发式，不等同于样本外预测。",
        "- 若 >=1000x 分桶显著跑赢，应保留极端热度加权；若 200-1000x 与 >=1000x 分化不大，应降低边际加分。",
        "- 破发样本需单独复盘行业、估值和发行结构，避免只按热度打分。",
        "",
        render_data_source_note(summary),
    ]
    return "\n".join(lines)


def write_csv(samples: Iterable[IpoSample], path: str) -> None:
    rows = [asdict(sample) for sample in samples]
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest recent HK IPO debut returns.")
    parser.add_argument(
        "--limit", type=int, default=100, help="number of recent listed IPOs to fetch"
    )
    parser.add_argument("--source", choices=["aastocks"], default="aastocks")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--csv", help="optional CSV output path for raw samples")
    parser.add_argument(
        "--enrichment-csv",
        help="optional CSV with code,industry,greenshoe,cornerstone,grey_market_return_pct",
    )
    parser.add_argument("--enrichment-source", choices=["none", "xinguyufu"], default="none")
    parser.add_argument(
        "--enrichment-delay",
        type=float,
        default=0.1,
        help="delay between public enrichment API requests",
    )
    parser.add_argument(
        "--debut-price-source", choices=["listed-table", "futu-kline"], default="listed-table"
    )
    parser.add_argument(
        "--futu-host",
        default="127.0.0.1",
        help="Futu OpenD host for --debut-price-source futu-kline",
    )
    parser.add_argument(
        "--futu-port",
        type=int,
        default=11111,
        help="Futu OpenD port for --debut-price-source futu-kline",
    )
    parser.add_argument(
        "--futu-delay",
        type=float,
        default=0.55,
        help="delay between Futu historical K-line requests",
    )
    parser.add_argument(
        "--api-root", help="stock-analysis-api root for --debut-price-source futu-kline"
    )
    parser.add_argument("--uv", help="uv executable for --debut-price-source futu-kline")
    args = parser.parse_args()
    try:
        samples = load_aastocks_samples(args.limit, load_enrichment(args.enrichment_csv))
        if args.enrichment_source == "xinguyufu":
            updated = apply_xinguyufu_enrichment(samples, delay=args.enrichment_delay)
            print(f"新股渔夫补充字段覆盖：{updated}/{len(samples)}", file=sys.stderr)
        if args.debut_price_source == "futu-kline":
            updated = apply_futu_debut_returns(
                samples,
                delay=args.futu_delay,
                host=args.futu_host,
                port=args.futu_port,
                api_root=args.api_root,
                uv_path=args.uv,
            )
            print(
                f"stock-analysis-api Futu CLI 首日 K 线覆盖：{updated}/{len(samples)}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"回测数据抓取失败：{exc}", file=sys.stderr)
        return 1
    summary = summarize(samples)
    if args.csv:
        write_csv(samples, args.csv)
    if args.format == "json":
        print(
            json.dumps(
                {"samples": [asdict(sample) for sample in samples], "summary": summary},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
