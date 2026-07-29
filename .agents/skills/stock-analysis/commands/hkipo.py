#!/usr/bin/env python3
"""Skill command executor for /hkipo."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from env_loader import api_root_candidates, effective_skill_env

FUTU_MARKET_DATA_SCRIPT = Path("scripts") / "futu_market_data.py"
INCLUDE_ALL_FLAG = "--all"


@dataclass(frozen=True)
class FutuIpoCommand:
    command: str | None
    api_root: Path | None
    uv_path: Path | None
    reason: str | None


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def resolve_skill_dir(
    skill_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    if skill_dir:
        return Path(skill_dir).expanduser().resolve()
    resolved_env = os.environ if env is None else env
    env_skill_dir = resolved_env.get("AGENT_FABRIC_SKILL_DIR")
    if env_skill_dir:
        return Path(env_skill_dir).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def _path_from_env_executable(value: str, env: Mapping[str, str] | None = None) -> Path | None:
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


def candidate_uv_paths(env: Mapping[str, str] | None = None) -> list[Path]:
    resolved_env = os.environ if env is None else env
    candidates: list[Path] = []
    for env_name in ("STOCK_ANALYSIS_UV", "UV_BIN", "UV"):
        uv_path = _path_from_env_executable(resolved_env.get(env_name, ""), env=env)
        if uv_path:
            candidates.append(uv_path)
    path_uv = shutil.which("uv", path=None if env is None else resolved_env.get("PATH", ""))
    if path_uv:
        candidates.append(Path(path_uv).expanduser().resolve())
    home_value = resolved_env.get("HOME") or str(Path.home())
    if home_value:
        home = Path(home_value).expanduser()
        candidates.extend([home / ".local" / "bin" / "uv", home / ".cargo" / "bin" / "uv"])

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def candidate_api_roots(
    skill_dir: Path,
    home_dir: Path,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    return api_root_candidates(skill_dir, env=env, home_dir=home_dir)


def _valid_futu_api_root(path: Path) -> Path | None:
    root = path.expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    root = root.resolve()
    if (root / FUTU_MARKET_DATA_SCRIPT).is_file():
        return root
    return None


def resolve_futu_ipo_command(
    skill_dir: str | Path | None = None,
    home_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> FutuIpoCommand:
    resolved_skill_dir = resolve_skill_dir(skill_dir, env=env)
    resolved_env = effective_skill_env(resolved_skill_dir, env=env)
    resolved_home_dir = (
        Path(home_dir).expanduser().resolve()
        if home_dir
        else Path(resolved_env.get("HOME") or str(Path.home())).expanduser().resolve()
    )
    uv_path = candidate_uv_paths(env=resolved_env)
    resolved_uv_path = uv_path[0] if uv_path else None
    api_root = None
    for candidate in candidate_api_roots(resolved_skill_dir, resolved_home_dir, env=resolved_env):
        api_root = _valid_futu_api_root(candidate)
        if api_root:
            break

    if not api_root:
        return FutuIpoCommand(
            command=None,
            api_root=None,
            uv_path=resolved_uv_path,
            reason="未找到 stock-analysis-api 仓库或 scripts/futu_market_data.py",
        )
    if not resolved_uv_path:
        return FutuIpoCommand(
            command=None,
            api_root=api_root,
            uv_path=None,
            reason=(
                "未找到 uv 可执行文件；请设置 STOCK_ANALYSIS_UV / UV_BIN，"
                "或确保 HOME 下存在 .local/bin/uv / .cargo/bin/uv"
            ),
        )

    command = (
        f"cd {shlex.quote(str(api_root))} && "
        f"{shlex.quote(str(resolved_uv_path))} run python "
        "scripts/futu_market_data.py ipo-list --market HK --json"
    )
    return FutuIpoCommand(
        command=command,
        api_root=api_root,
        uv_path=resolved_uv_path,
        reason=None,
    )


def format_futu_instruction(futu_command: FutuIpoCommand) -> str:
    if futu_command.command:
        return (
            f"stock-analysis-api Futu CLI：`{futu_command.command}`。"
            "这条命令由 /hkipo executor 运行时解析，必须直接复制执行；"
            "不要改用当前工作区 `.venv/bin/python`、系统 Python 或其他脚本。"
        )

    return (
        f"stock-analysis-api Futu CLI 预检：{futu_command.reason}。不要在当前工作区"
        "猜测 `.venv/bin/python`；此时才允许按 Futu/OpenD 不可用处理，并用 HKEX / "
        "公司公告 / 财经站补齐。"
    )


def parse_command_args(payload: dict) -> list[str]:
    raw_args = payload.get("args")
    if isinstance(raw_args, list):
        return [str(arg) for arg in raw_args]

    args_text = payload.get("argsText")
    if isinstance(args_text, str) and args_text.strip():
        try:
            return shlex.split(args_text)
        except ValueError:
            return args_text.split()

    return []


def should_include_closed_ipos(payload: dict) -> bool:
    return INCLUDE_ALL_FLAG in parse_command_args(payload)


def build_prompt(
    payload: dict,
    skill_dir: str | Path | None = None,
    home_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    workspace = payload.get("workspace") or {}
    workspace_name = workspace.get("name") or workspace.get("folder") or "当前工作区"
    futu_instruction = format_futu_instruction(
        resolve_futu_ipo_command(skill_dir=skill_dir, home_dir=home_dir, env=env)
    )
    include_closed = should_include_closed_ipos(payload)
    if include_closed:
        pool_goal = "输出当前仍可认购 + 已截止认购但未上市的港股 IPO；不要求用户提供代码。"
        pool_filter = (
            "用户已显式传入 `--all`：保留 `is_subscribe_status=false` "
            "且上市日未到的标的，并明确标注已截止/暗盘/上市日。"
        )
    else:
        pool_goal = "默认只输出当前仍可认购的港股 IPO；不要求用户提供代码。"
        pool_filter = (
            "默认过滤 `is_subscribe_status=false` 的已截止新股；即使其尚未上市，也不要"
            "放入本次优先级字段块。只有用户使用 `/hkipo --all` 时才纳入。"
        )

    return f"""今天是 {today}。这是由 stock-analysis-skill 的 /hkipo 触发的港股 IPO 池研究任务，当前工作区为：{workspace_name}。

任务目标
- {pool_goal}
- 输出极简打新优先级：用窄字段列表展示每只 IPO 的综合评分、申购截止/开奖日期、融资倍数/认购热度、绿鞋/基石、首日回测映射。
- 如果当前没有符合条件的标的，明确写出“当前无符合条件的港股 IPO 池”。

执行要求
- 必须联网核验当前状态，并使用绝对日期表述关键时间点。
- 必须按 {today} 重新获取最新数据；不允许把旧日期的孖展、公开认购、暗盘或中签率当作当前数据使用。若只能找到旧数据，必须标注来源日期并写明“过期/仅供趋势参考”，不得用于当前热度主评分。
- 不要解释触发文本、系统日期或取数过程；若用户消息里的日期与 {today} 不一致，直接按 {today} 输出，不写日期差异说明。
- IPO 池范围：{pool_filter}
- 当前 IPO 池发现、招股状态、上市日、招股截止日、发售价、一手股数和入场费必须优先使用 Futu/OpenD 只读接口：{futu_instruction}只有当 Futu/OpenD 不可用、返回空值或字段为 N/A 时，才允许用外部数据源补齐，并在 Sources 中标注“Futu 缺字段，外部源补充”。
- 招股书、全球发售、配发结果、上市文件、公司公告等事实层优先使用 HKEX / 公司公告；财经站只用于补充 Futu/OpenD 和一手来源未提供的公开发售倍数、孖展/认购热度、中签率、一手中签率、灰市、首日涨幅等二级数据。
- 开放认购中的 IPO 热度必须通过当日硬门槛：每只池内 IPO 进入评分前，必须按代码、中文名和英文名自动重试检索，至少检索 3 类权威来源（券商新股中心 / 券商孖展表、财经门户新股频道、主流行情 App 新股页或 HKEX / 公司公告时间表；例如富途牛牛、辉立 POEMS、华盛通、老虎、AAStocks、ETNet、新浪港股 / 智通、格隆汇）。优先取 {today} 当日且更新时间最晚的孖展 / 公开认购 / 暗盘数据；不得把前一日或更旧孖展倍率用于主评分。
- 最新热度必须做多权威机构聚合，不允许死用单一来源：Futu CLI 不暴露 App 新股热度时，必须继续查 Futu/牛牛新股页或相关内容，再查 TradeGo / 活报告等多券商聚合、新股孖展统计、AAStocks、ETNet、智通 / 新浪、格隆汇，以及华盛、老虎、辉立、耀才、致富、KGI 等券商新股中心 / 孖展表。
- 同日冲突时，优先取同日多券商汇总或明确为全市场 / 多券商聚合的最新值；不得把单一券商孖展下限当作全市场主热度，也不得用单一券商额度替代 Futu App 或多券商聚合值。单一券商数值只能写成“单一券商下限 / 趋势参考”，除非已经完成多源检索且没有更权威的同日聚合源。
- 热度字段必须按固定顺序核验：先用 Futu/OpenD 当前字段和 Futu App / 牛牛热度，再查同日多券商汇总 / 全市场聚合，再查同一 IPO 当日券商新股中心 / 孖展表，再查当日财经门户新股频道的公开认购倍数 / 一手中签率，最后才用暗盘或其他二级热度。每个孖展 / 公开认购 / 暗盘数值都必须标注来源更新时间；同一字段多个来源冲突时，用更新时间最新且不晚于 {today} 的数值，旧值只可写“过期/仅供趋势参考”，不得进入当前热度主评分。
- 输出前必须做一次同日冲突复查：用代码、中文名、英文名分别组合“孖展 / 融资 / 认购 / 倍 / 公开发售 / 暗盘”和 {today} 搜索；若发现更晚来源，必须替换热度主字段。若多源重试后仍无当日热度，热度字段写“热度未达当日核验门槛”，Subscription Heat 按缺失当前热度处理。
- 必须读取并遵循 stock-analysis-skill 的 `references/hkipo.md`：按 0-100 加权评分，覆盖融资/认购热度、发行结构、回测适配、基本面、估值、证据质量；若已进入暗盘后待上市阶段，暗盘涨幅是最强近端信号。
- 发行结构必须检查绿鞋/超额配股权、稳定价格操作人、基石质量与占比、保荐人、回拨/公众货比例。
- 个股标题末尾必须写申购截止日和开奖/配发结果日，用 `M/D截止 | M/D开奖` 格式；例如 `🟡 2｜01236 樂動機器人｜74｜5/6截止 | 5/7开奖`。标题末尾不要写建议性措辞、跟踪标签或“优先级”文字。
- 回测校准只保留关键映射结论，写入每只 IPO 的“回测”字段；不要单列推导过程。
- 不输出目标价、确定性承诺、买卖指令或建议性结论；分数只表达为打新/首日赔率排序。
- 报告正文不要使用 Markdown 大标题 `#` / `##`；使用普通加粗标签和短分隔。
- 报告正文不要使用宽 Markdown 表格；每只 IPO 用紧凑字段块展示。
- 正文不要插入空白空行；顶层小节标题、bullet、个股标题和个股字段都用单换行连续排列。
- 用固定 emoji 强化重点：🟢 池内最高，🟡 观察，⚪ 谨慎；💰 热度，🛡 结构，📈 回测，⚠️ 风险，🔗 来源。
- 输出必须短：除 Sources 外，不写字段块外的逐票解释；结论先行最多 3 条 bullet。

输出格式
**港股 IPO 池｜{today}**
----
**💡 关键结论**
- 🟢 最值得跟踪：代码 公司，关键理由。
- 🟡 观察：代码 公司，关键理由。
- ⚪ 谨慎/观察：代码 公司，关键理由。
**📌 优先级**
**🟢 1｜代码 公司｜评分｜M/D截止 | M/D开奖**
📍 阶段：招股/截止/暗盘/上市日；Futu：发售价/一手/入场费/状态
💰 热度：最新孖展/公开认购/暗盘，标注日期和是否外部补充
🛡 结构：绿鞋/基石/保荐/回拨
📈 回测：对应热度分桶和首日赔率映射
⚠️ 风险：一句话最大风险
**🔗 来源**
- 只列关键链接；每个标的最多 2-3 个 Markdown 短链接，标明用途、发布日期/更新时间、Futu 当前字段或外部补充字段。"""


def build_workflow_reply(payload: dict) -> dict:
    include_closed = should_include_closed_ipos(payload)
    args_text = payload.get("argsText") if isinstance(payload.get("argsText"), str) else ""
    return {
        "reply": {
            "type": "workflow",
            "workflowId": "hkipo",
            "prompt": "港股 IPO 打新分析",
            "input": {
                "command": "hkipo",
                "includeClosed": include_closed,
                "argsText": args_text,
            },
            "ack": "已启动港股 IPO 工作流，正在获取 IPO 池、补齐孖展/认购热度并生成简明报告。",
        }
    }


def main() -> None:
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    emit(build_workflow_reply(payload))


if __name__ == "__main__":
    main()
