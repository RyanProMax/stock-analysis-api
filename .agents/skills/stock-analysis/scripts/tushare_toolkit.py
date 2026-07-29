#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare 工具集：

- `.env` 加载与 Tushare Pro 初始化
- 股票 / ETF 代码标准化与 ts_code 推断
- 根目录 references 与单一接口总表生成
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import re
from typing import Any, Callable, Optional

from dotenv import load_dotenv
import pandas as pd
import tushare as ts

SH_PREFIXES = ("60", "68", "51", "52", "56", "58")
SZ_PREFIXES = ("00", "30", "15", "16", "18")
ETF_PREFIXES = ("51", "52", "56", "58", "15", "16", "18")
REFERENCE_INDEX_PATH = "references/api_reference.md"
CN_STOCK_INFO_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date"
)
US_STOCK_INFO_FIELDS = "ts_code,name,enname,classify,list_date,delist_date"
SOURCE_STATUS_OK = "ok"
SOURCE_STATUS_PERMISSION_DENIED = "permission_denied"
SOURCE_STATUS_ERROR = "error"
SOURCE_STATUS_UNAVAILABLE = "unavailable"
SOURCE_STATUS_NOT_IMPLEMENTED = "not_implemented"


class Node:
    id: int
    parent_id: int
    is_doc: bool
    key: str
    title: str
    desc: str = ""
    name: str
    dir_path: str
    file_path: str
    content: str
    children: list["Node"]
    categories: list[str]


def _load_env_files():
    seen = set()
    script_path = Path(__file__).resolve()
    candidates = [Path.cwd() / ".env"]
    for directory in script_path.parents:
        if (directory / "SKILL.md").is_file() or (directory / "pyproject.toml").is_file():
            candidates.append(directory / ".env")
    for env_path in candidates:
        resolved = env_path.resolve()
        if resolved in seen or not env_path.exists():
            continue
        load_dotenv(env_path, override=False)
        seen.add(resolved)


def get_tushare_pro():
    """从环境变量初始化 Tushare Pro 实例。"""
    _load_env_files()

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    http_url = os.environ.get("TUSHARE_HTTP_URL", "").strip()

    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN，请先在 .env 或环境变量中配置。")

    pro = ts.pro_api("anything")
    setattr(pro, "_DataApi__token", token)
    if http_url:
        setattr(pro, "_DataApi__http_url", http_url)
    return pro


def normalize_symbol(raw_symbol: str) -> Optional[str]:
    """标准化 A 股 / ETF 代码，仅保留 6 位数字代码。"""
    normalized = re.sub(r"[^0-9A-Za-z.]", "", str(raw_symbol or "").strip().upper())
    if not normalized:
        return None
    if normalized.endswith((".SH", ".SZ")):
        normalized = normalized.rsplit(".", 1)[0]
    if normalized.isdigit() and len(normalized) == 6:
        return normalized
    return None


def infer_exchange(symbol: str) -> str:
    """根据代码前缀推断交易所。"""
    if symbol.startswith(SH_PREFIXES):
        return "SH"
    if symbol.startswith(SZ_PREFIXES):
        return "SZ"
    raise ValueError(f"无法根据代码推断交易所: {symbol}")


def build_ts_code(symbol: str) -> str:
    """构造 Tushare 使用的 ts_code。"""
    normalized = normalize_symbol(symbol)
    if not normalized:
        raise ValueError(f"非法证券代码: {symbol}")
    return f"{normalized}.{infer_exchange(normalized)}"


def build_legacy_symbol(symbol: str) -> str:
    """构造 Tushare 旧版实时接口使用的代码。"""
    normalized = normalize_symbol(symbol)
    if not normalized:
        raise ValueError(f"非法证券代码: {symbol}")
    return f"{infer_exchange(normalized).lower()}{normalized}"


def infer_security_type(symbol: str) -> str:
    """区分股票与 ETF。"""
    normalized = normalize_symbol(symbol)
    if not normalized:
        raise ValueError(f"非法证券代码: {symbol}")
    if normalized.startswith(ETF_PREFIXES):
        return "etf"
    return "stock"


def percent_to_ratio(value) -> Optional[float]:
    """把百分比数值标准化为 ratio。"""
    if value is None or value == "":
        return None
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return None


def parse_df_recursive(
    df: pd.DataFrame,
    parent_id: int,
    parent_titles: list[str],
    docs: Optional[list[dict]] = None,
    path: str = "",
) -> list[Node]:
    nodes: list[Node] = []
    for _, row in df[df["PARENT_ID"] == parent_id].iterrows():
        node = Node()
        node.id = row["ID"]
        node.parent_id = parent_id
        node.is_doc = row["IS_DOC"]
        node.title = row["TITLE"]
        node.name = row["TITLE"]
        node.dir_path = os.path.join(path, node.name)
        node.file_path = os.path.join(path, f"{node.name}.md")
        node.content = row["SRC_CONTENT"]
        node.categories = parent_titles
        if isinstance(node.content, str):
            key_match = (
                re.search(r"接口[:： ]+(?P<key>[a-zA-Z0-9_]+)", node.content)
                or re.search(r"\*\*接口名称\*\*[:： ]+(?P<key>[a-zA-Z0-9_]+)", node.content)
                or re.search(r"\*\*接口\*\*[:： ]+(?P<key>[a-zA-Z0-9_]+)", node.content)
            )
            if key_match:
                node.key = key_match.group("key").strip()
            desc_match = re.search(r"描述[:： ]+(?P<desc>.+)\n", node.content)
            if desc_match:
                node.desc = desc_match.group("desc").strip()
        nodes.append(node)
        if node.is_doc and isinstance(docs, list):
            docs.append(
                {
                    "id": node.id,
                    "key": node.key,
                    "title": f"[{node.name}]({node.file_path})",
                    "categories": ",".join(node.categories),
                    "desc": node.desc,
                }
            )
        node.children = parse_df_recursive(
            df,
            node.id,
            parent_titles + [node.name],
            docs,
            node.dir_path,
        )
    return nodes


def create_dir_file_recursive(children: list[Node], path: str):
    for child in children:
        if child.is_doc:
            with open(os.path.join(path, child.file_path), "w", encoding="utf-8") as file:
                file.write(child.content)
        else:
            os.makedirs(os.path.join(path, child.dir_path), exist_ok=True)
            create_dir_file_recursive(child.children, path)


def parse_reference_index(reference_index_path: str = REFERENCE_INDEX_PATH) -> list[dict]:
    """从单一接口总表解析接口索引，兼容旧版与新版表结构。"""
    index_path = Path(reference_index_path)
    if not index_path.exists():
        raise FileNotFoundError(f"未找到接口总表: {reference_index_path}")

    rows: list[dict] = []
    for raw_line in index_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        if "接口" in line and "标题" in line and "分类" in line and "描述" in line:
            continue
        if re.fullmatch(r"\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|", line):
            continue

        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) == 4:
            interface_cell, title_cell, category_cell, desc_cell = parts
            row_id = len(rows) + 1
        elif len(parts) == 5:
            row_id_cell, interface_cell, title_cell, category_cell, desc_cell = parts
            row_id = int(row_id_cell) if row_id_cell.isdigit() else len(rows) + 1
        else:
            continue

        title_link_match = re.search(r"\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)", title_cell)
        interface_link_match = re.search(r"\[(?P<key>[^\]]+)\]\((?P<url>[^)]+)\)", interface_cell)

        if title_link_match:
            key = interface_cell.strip()
            title = title_link_match.group("title").strip()
            url = title_link_match.group("url").strip()
        elif interface_link_match:
            key = interface_link_match.group("key").strip()
            title = title_cell or key
            url = interface_link_match.group("url").strip()
        else:
            continue

        desc = desc_cell.replace("<br />", "").strip()
        rows.append(
            {
                "ID": row_id,
                "接口名": key,
                "标题(详细文档)": f"[{title}]({url})",
                "分类": category_cell,
                "描述": desc,
            }
        )
    return rows


def write_reference_index(rows: list[dict], reference_index_path: str):
    """写入单一接口总表。"""
    index_file = Path(reference_index_path)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    columns = ["ID", "接口名", "标题(详细文档)", "分类", "描述"]

    def stringify(value: Any) -> str:
        if value is None:
            return ""
        return str(value).replace("\n", " ").strip()

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    table_lines = [header, separator]
    for row in rows:
        table_lines.append(
            "| " + " | ".join(stringify(row.get(column, "")) for column in columns) + " |"
        )

    content = "# API Reference\n\n由 `python scripts/tushare_toolkit.py generate-docs` 生成。\n\n"
    content += "\n".join(table_lines)
    content += "\n"
    index_file.write_text(content, encoding="utf-8")


def generate_reference_docs(
    csv_path: str = "data/api-doc.csv.csv",
    output_root: str = ".",
    reference_index_path: str = REFERENCE_INDEX_PATH,
) -> int:
    """根据本地 CSV 生成 references/ 与单一接口总表，缺失时回退到现有总表。"""
    csv_file = Path(csv_path)
    if not csv_file.exists():
        rows = parse_reference_index(reference_index_path)
        write_reference_index(rows, reference_index_path)
        return len(rows)

    df = pd.read_csv(csv_file)
    df["TITLE"] = df["TITLE"].str.replace(r'[<>:"/\\|?*]', "", regex=True)
    df["TITLE"] = df["TITLE"].str.replace("（", "(").str.replace("）", ")")
    df = df.drop(
        df[
            df["TITLE"].isin(
                [
                    "历史Tick行情",
                    "实时Tick(爬虫)",
                    "实时成交(爬虫)",
                    "实时排名(爬虫)",
                ]
            )
        ].index
    )
    doc_ids = set(df["PARENT_ID"].tolist())
    df["IS_DOC"] = ~df["ID"].isin(doc_ids)

    docs: list[dict] = []
    nodes = parse_df_recursive(df, 2, [], docs, "references")
    create_dir_file_recursive(nodes, output_root)

    df_md = pd.DataFrame(docs)
    df_md.sort_values(by=["categories"], inplace=True)
    df_md.rename(
        columns={
            "id": "ID",
            "title": "标题(详细文档)",
            "key": "接口名",
            "categories": "分类",
            "desc": "描述",
        },
        inplace=True,
    )
    write_reference_index(df_md.to_dict(orient="records"), reference_index_path)
    return len(docs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tushare 内部工具集")
    subparsers = parser.add_subparsers(dest="command")

    generate_docs = subparsers.add_parser(
        "generate-docs", help="根据本地 CSV 生成 references/ 与单一接口总表"
    )
    generate_docs.add_argument(
        "--csv-path",
        default="data/api-doc.csv.csv",
        help="本地接口文档 CSV 路径",
    )
    generate_docs.add_argument(
        "--reference-index",
        default=REFERENCE_INDEX_PATH,
        help="接口总表输出路径；缺失 CSV 时也会从该文件回退读取",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command != "generate-docs":
        print("请使用: python scripts/tushare_toolkit.py generate-docs", flush=True)
        return 2

    try:
        generated_count = generate_reference_docs(
            csv_path=args.csv_path,
            reference_index_path=args.reference_index,
        )
    except FileNotFoundError as exc:
        print(str(exc), flush=True)
        return 3

    print(f"已生成 {generated_count} 篇接口文档，并更新 {args.reference_index}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
