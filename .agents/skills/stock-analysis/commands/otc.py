#!/usr/bin/env python3
"""Skill command executor for /otc."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from env_loader import api_root_candidates, effective_skill_env

GREY_MARKET_WATCH_SCRIPT = Path("scripts") / "grey_market_watch.py"
DEFAULT_ACTIVE_WINDOW = "16:15-18:30"
DEFAULT_PROVIDERS = "futu,tiger,fosun"
DEFAULT_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True)
class OtcRequest:
    code: str
    display_code: str
    name: str | None
    issue_price: float | None
    providers: str
    loop_seconds: int | None


@dataclass(frozen=True)
class OtcApiCommand:
    command: str | None
    api_root: Path | None
    uv_path: Path | None
    reason: str | None


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def usage(message: str | None = None) -> dict:
    prefix = f"{message}\n\n" if message else ""
    return {
        "reply": {
            "type": "final_markdown",
            "content": (
                f"{prefix}用法：`/otc <港股代码> [--loop=300s]`\n\n"
                "示例：\n"
                "- `/otc 07666.HK`\n"
                "- `/otc HK.07666`\n"
                "- `/otc 07666.HK --loop=300s`"
            ),
        }
    }


def parse_command_args(payload: dict) -> list[str]:
    raw_args = payload.get("args")
    if isinstance(raw_args, list):
        return [str(arg).strip() for arg in raw_args if str(arg).strip()]

    args_text = str(payload.get("argsText") or "").strip()
    if not args_text:
        return []
    try:
        return [part for part in shlex.split(args_text) if part]
    except ValueError:
        return [part for part in args_text.split() if part]


def normalize_hk_symbol(raw_symbol: str) -> tuple[str, str] | None:
    symbol = str(raw_symbol or "").strip().upper()
    if not symbol:
        return None

    digits: str | None = None
    if symbol.startswith("HK."):
        digits = symbol[3:]
    elif symbol.endswith(".HK"):
        digits = symbol[:-3]
    elif symbol.isdigit():
        digits = symbol

    if not digits or not re.fullmatch(r"\d{1,5}", digits):
        return None
    padded = digits.zfill(5)
    return f"HK.{padded}", f"{padded}.HK"


def parse_duration_seconds(raw_value: str) -> int | None:
    value = str(raw_value or "").strip().lower()
    if not value:
        return None
    multiplier = 1
    if value.endswith("s"):
        value = value[:-1]
    elif value.endswith("m"):
        value = value[:-1]
        multiplier = 60
    if not re.fullmatch(r"\d+", value):
        return None
    seconds = int(value) * multiplier
    return seconds if seconds > 0 else None


def parse_request(payload: dict) -> OtcRequest | str:
    args = parse_command_args(payload)
    symbol: str | None = None
    loop_seconds: int | None = None
    providers = DEFAULT_PROVIDERS
    name: str | None = None
    issue_price: float | None = None

    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith("--loop="):
            loop_seconds = parse_duration_seconds(arg.split("=", 1)[1])
            if loop_seconds is None:
                return "`--loop` 需要是正整数秒或分钟，例如 `--loop=300s`。"
        elif arg == "--loop":
            if index + 1 >= len(args):
                return "`--loop` 缺少间隔，例如 `--loop 300s`。"
            loop_seconds = parse_duration_seconds(args[index + 1])
            if loop_seconds is None:
                return "`--loop` 需要是正整数秒或分钟，例如 `--loop=300s`。"
            index += 1
        elif arg.startswith("--providers="):
            providers = arg.split("=", 1)[1].strip() or DEFAULT_PROVIDERS
        elif arg == "--providers":
            if index + 1 >= len(args):
                return "`--providers` 缺少 provider 列表。"
            providers = args[index + 1].strip() or DEFAULT_PROVIDERS
            index += 1
        elif arg.startswith("--name="):
            name = arg.split("=", 1)[1].strip() or None
        elif arg == "--name":
            if index + 1 >= len(args):
                return "`--name` 缺少展示名。"
            name = args[index + 1].strip() or None
            index += 1
        elif arg.startswith("--issue-price="):
            try:
                issue_price = float(arg.split("=", 1)[1])
            except ValueError:
                return "`--issue-price` 需要是数字。"
        elif arg == "--issue-price":
            if index + 1 >= len(args):
                return "`--issue-price` 缺少发行价。"
            try:
                issue_price = float(args[index + 1])
            except ValueError:
                return "`--issue-price` 需要是数字。"
            index += 1
        elif arg.startswith("--"):
            return f"暂不支持参数 `{arg}`。"
        elif symbol is None:
            symbol = arg
        else:
            return "一次 `/otc` 只支持查询一只港股代码。"
        index += 1

    if symbol is None:
        return "请提供港股代码。"
    normalized = normalize_hk_symbol(symbol)
    if normalized is None:
        return "港股代码格式不正确，请使用 `07666.HK` 或 `HK.07666`。"
    code, display_code = normalized
    return OtcRequest(
        code=code,
        display_code=display_code,
        name=name,
        issue_price=issue_price,
        providers=providers,
        loop_seconds=loop_seconds,
    )


def _parse_windows(raw_windows: str) -> list[tuple[time, time]]:
    windows: list[tuple[time, time]] = []
    for raw_part in str(raw_windows or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError("active window must use HH:MM-HH:MM")
        raw_start, raw_end = part.split("-", 1)
        start = time.fromisoformat(raw_start.strip())
        end = time.fromisoformat(raw_end.strip())
        if start >= end:
            raise ValueError("active window start must be earlier than end")
        windows.append((start, end))
    if not windows:
        raise ValueError("active window must include at least one entry")
    return windows


def is_inside_window(now: datetime, active_window: str = DEFAULT_ACTIVE_WINDOW) -> bool:
    current = now.timetz().replace(tzinfo=None)
    return any(start <= current <= end for start, end in _parse_windows(active_window))


def next_window_start(now: datetime, active_window: str = DEFAULT_ACTIVE_WINDOW) -> datetime:
    current = now.timetz().replace(tzinfo=None)
    windows = sorted(_parse_windows(active_window))
    for start, _end in windows:
        if current < start:
            return now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    start = windows[0][0]
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)


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


def _valid_api_root(path: Path) -> Path | None:
    root = path.expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    root = root.resolve()
    if (root / GREY_MARKET_WATCH_SCRIPT).is_file():
        return root
    return None


def resolve_api_command(
    request: OtcRequest,
    *,
    skill_dir: str | Path | None = None,
    home_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> OtcApiCommand:
    resolved_skill_dir = resolve_skill_dir(skill_dir, env=env)
    resolved_env = effective_skill_env(resolved_skill_dir, env=env)
    resolved_home_dir = (
        Path(home_dir).expanduser().resolve()
        if home_dir
        else Path(resolved_env.get("HOME") or str(Path.home())).expanduser().resolve()
    )
    uv_candidates = candidate_uv_paths(env=resolved_env)
    uv_path = uv_candidates[0] if uv_candidates else None

    api_root = None
    for candidate in candidate_api_roots(resolved_skill_dir, resolved_home_dir, env=resolved_env):
        api_root = _valid_api_root(candidate)
        if api_root:
            break

    if not api_root:
        return OtcApiCommand(
            command=None,
            api_root=None,
            uv_path=uv_path,
            reason="未找到 stock-analysis-api 仓库或 scripts/grey_market_watch.py",
        )
    if not uv_path:
        return OtcApiCommand(
            command=None,
            api_root=api_root,
            uv_path=None,
            reason=(
                "未找到 uv 可执行文件；请设置 STOCK_ANALYSIS_UV / UV_BIN，"
                "或确保 HOME 下存在 .local/bin/uv / .cargo/bin/uv"
            ),
        )

    command_args = [
        shlex.quote(str(uv_path)),
        "run",
        "python",
        "scripts/grey_market_watch.py",
        "--code",
        shlex.quote(request.code),
        "--providers",
        shlex.quote(request.providers),
        "--json",
    ]
    if request.name:
        command_args.extend(["--name", shlex.quote(request.name)])
    if request.issue_price is not None:
        command_args.extend(["--issue-price", shlex.quote(str(request.issue_price))])
    if request.loop_seconds is None:
        command_args.append("--once")
    else:
        command_args.extend(["--interval-seconds", str(request.loop_seconds)])

    command = f"cd {shlex.quote(str(api_root))} && {' '.join(command_args)}"
    return OtcApiCommand(command=command, api_root=api_root, uv_path=uv_path, reason=None)


def build_prompt(
    request: OtcRequest,
    command: OtcApiCommand,
    now: datetime,
    payload: dict,
) -> str:
    workspace = payload.get("workspace") or {}
    workspace_name = workspace.get("name") or "未命名工作区"
    mode = "单次查询" if request.loop_seconds is None else f"{request.loop_seconds}s 轮询 tick"
    loop_rule = (
        "这是单次查询：必须执行带 `--once` 的 API 命令，不能被历史 scheduler tick 状态挡住。"
        if request.loop_seconds is None
        else (
            f"这是轮询查询：把 `--loop={request.loop_seconds}s` 映射为 API "
            f"`--interval-seconds {request.loop_seconds}`。若宿主支持定时任务，按该间隔重复触发"
            "同一条命令直到暗盘窗口结束；若当前 tick 返回 `not_due`，直接提示下一次到点时间。"
        )
    )
    return f"""今天是 {now.date().isoformat()}。这是由 stock-analysis-skill 的 /otc 触发的港股 IPO 暗盘 / OTC 只读查询任务，当前工作区为：{workspace_name}。

请求
- 标的：{request.display_code}（API code: `{request.code}`）
- 模式：{mode}
- 暗盘窗口：北京时间 {DEFAULT_ACTIVE_WINDOW}
- 时段预检：当前北京时间 {now.strftime("%H:%M:%S")}，已在暗盘窗口内。

执行要求
- 必须执行这条 API 命令：`{command.command}`。
- {loop_rule}
- API 返回 `outside_active_window` 时直接结束，提示当前不在暗盘窗口和 `next_run_at`。
- API 返回 `not_due` 时直接提示尚未到下一次轮询，不要绕过节流。
- API 返回 `ok` 时只输出用户需要看的 provider 报价摘要：provider、价格、bid/ask、相对发行价涨跌幅、暗盘状态、unsupported/failed 原因。
- Tiger / Fosun 等 provider 如果返回 `unsupported`，必须如实写“未接入正式授权 API”，不得网页抓取或补编报价。
- 只读查询；不得下单、改单、撤单、交易解锁、订阅推送或写券商状态。
- 不输出买卖建议、确定性承诺或交易指令；不要把单一 provider 报价写成全市场暗盘价。

输出格式
**/otc｜{request.display_code} 暗盘**
- 模式：{mode}
- 状态：ok / skipped / failed
- 概览：Futu/Tiger/Fosun 可用数、不可用数、失败数
- 报价：按 provider 分行列出；无正式 API 的 provider 写 unsupported 原因
- 下次：轮询模式才写下一次 tick 时间；单次查询不写下一次"""


def outside_window_reply(now: datetime) -> dict:
    next_start = next_window_start(now)
    return {
        "reply": {
            "type": "final_markdown",
            "content": (
                "**/otc｜未到暗盘时段**\n"
                f"当前北京时间 {now.strftime('%Y-%m-%d %H:%M:%S')}，"
                f"不在暗盘查询窗口 {DEFAULT_ACTIVE_WINDOW}。\n"
                f"下次窗口：{next_start.strftime('%Y-%m-%d %H:%M')} 北京时间。"
            ),
        }
    }


def build_reply(
    payload: dict,
    *,
    skill_dir: str | Path | None = None,
    home_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict:
    request_or_error = parse_request(payload)
    if isinstance(request_or_error, str):
        return usage(request_or_error)

    current = now or datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
    else:
        current = current.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
    if not is_inside_window(current):
        return outside_window_reply(current)

    request = request_or_error
    command = resolve_api_command(request, skill_dir=skill_dir, home_dir=home_dir, env=env)
    if not command.command:
        return {
            "reply": {
                "type": "final_markdown",
                "content": f"**/otc｜预检失败**\n{command.reason}",
            }
        }

    ack = (
        f"已开始查询 {request.display_code} 暗盘报价。"
        if request.loop_seconds is None
        else f"已开始按 {request.loop_seconds}s 轮询 {request.display_code} 暗盘报价。"
    )
    return {
        "reply": {
            "type": "assistant_prompt",
            "content": build_prompt(request, command, current, payload),
            "ack": ack,
        }
    }


def main() -> None:
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    emit(build_reply(payload))


if __name__ == "__main__":
    main()
