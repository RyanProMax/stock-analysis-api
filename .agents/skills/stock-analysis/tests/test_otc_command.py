import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "commands"))

import otc


class OtcCommandTest(unittest.TestCase):
    def _make_api_root(
        self, root: pathlib.Path
    ) -> tuple[pathlib.Path, pathlib.Path, dict[str, str]]:
        skill_dir = root / "stock-analysis-skill"
        api_root = root / "stock-analysis-api"
        script_path = api_root / "scripts" / "grey_market_watch.py"
        uv_path = root / "tooling" / "uv"
        skill_dir.mkdir(parents=True)
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
        uv_path.parent.mkdir(parents=True)
        uv_path.write_text("#!/bin/sh\n", encoding="utf-8")
        uv_path.chmod(0o755)
        return (
            skill_dir,
            uv_path,
            {
                "PATH": "",
                "HOME": str(root),
                "STOCK_ANALYSIS_UV": str(uv_path),
            },
        )

    def test_once_query_maps_hk_suffix_to_api_once_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir, uv_path, env = self._make_api_root(root)

            result = otc.build_reply(
                {"argsText": "07666.HK", "args": ["07666.HK"]},
                skill_dir=skill_dir,
                env=env,
                now=datetime(2026, 5, 12, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertEqual(reply["ack"], "已开始查询 07666.HK 暗盘报价。")
        self.assertIn("`HK.07666`", content)
        self.assertIn("07666.HK", content)
        self.assertIn(f"{otc.shlex.quote(str(uv_path))} run python", content)
        self.assertIn("scripts/grey_market_watch.py", content)
        self.assertIn("--code HK.07666", content)
        self.assertIn("--json --once", content)
        self.assertNotIn("--interval-seconds", content)
        self.assertIn("当前北京时间 16:30:00，已在暗盘窗口内", content)

    def test_loop_query_maps_to_interval_tick_without_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir, _uv_path, env = self._make_api_root(root)

            result = otc.build_reply(
                {"argsText": "HK.07666 --loop=300s", "args": ["HK.07666", "--loop=300s"]},
                skill_dir=skill_dir,
                env=env,
                now=datetime(2026, 5, 12, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertEqual(reply["ack"], "已开始按 300s 轮询 07666.HK 暗盘报价。")
        self.assertIn("--code HK.07666", content)
        self.assertIn("--interval-seconds 300", content)
        self.assertIn("300s 轮询 tick", content)
        self.assertNotIn("--once", content)
        self.assertIn("若当前 tick 返回 `not_due`", content)

    def test_outside_dark_window_exits_without_api_command(self) -> None:
        result = otc.build_reply(
            {"argsText": "07666.HK", "args": ["07666.HK"]},
            skill_dir=ROOT,
            env={"PATH": "", "HOME": "/tmp/no-home"},
            now=datetime(2026, 5, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "final_markdown")
        self.assertIn("未到暗盘时段", content)
        self.assertIn("当前北京时间 2026-05-12 15:00:00", content)
        self.assertIn("下次窗口：2026-05-12 16:15 北京时间", content)
        self.assertNotIn("grey_market_watch.py", content)

    def test_invalid_symbol_returns_usage(self) -> None:
        result = otc.build_reply({"argsText": "AAPL", "args": ["AAPL"]})

        reply = result["reply"]
        self.assertEqual(reply["type"], "final_markdown")
        self.assertIn("港股代码格式不正确", reply["content"])
        self.assertIn("/otc 07666.HK", reply["content"])

    def test_missing_api_root_reports_preflight_failure_inside_window(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir(parents=True)

            result = otc.build_reply(
                {"argsText": "07666.HK", "args": ["07666.HK"]},
                skill_dir=skill_dir,
                env={"PATH": "", "HOME": str(root)},
                now=datetime(2026, 5, 12, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

        reply = result["reply"]
        self.assertEqual(reply["type"], "final_markdown")
        self.assertIn("预检失败", reply["content"])
        self.assertIn("未找到 stock-analysis-api", reply["content"])

    def test_once_query_discovers_monorepo_api_root_without_api_env(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            api_root = pathlib.Path(raw_root).resolve() / "stock-analysis-api"
            skill_dir = api_root / ".agents" / "skills" / "stock-analysis"
            script_path = api_root / "scripts" / "grey_market_watch.py"
            uv_path = api_root / ".venv" / "bin" / "uv"
            skill_dir.mkdir(parents=True)
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")

            result = otc.build_reply(
                {"argsText": "07666.HK", "args": ["07666.HK"]},
                skill_dir=skill_dir,
                home_dir=api_root.parent,
                env={"STOCK_ANALYSIS_UV": str(uv_path)},
                now=datetime(2026, 5, 12, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

        content = result["reply"]["content"]
        self.assertEqual(result["reply"]["type"], "assistant_prompt")
        self.assertIn(f"cd {otc.shlex.quote(str(api_root))}", content)
        self.assertIn("scripts/grey_market_watch.py", content)

    def test_executor_main_emits_json_reply(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "commands" / "otc.py")],
            input=json.dumps({"argsText": "invalid", "args": ["invalid"]}),
            text=True,
            capture_output=True,
            check=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["reply"]["type"], "final_markdown")
        self.assertIn("港股代码格式不正确", payload["reply"]["content"])

    def test_commands_json_registers_otc(self) -> None:
        commands = json.loads((ROOT / "commands.json").read_text(encoding="utf-8"))

        command = commands["commands"]["otc"]
        self.assertEqual(command["executor"]["command"], "python3")
        self.assertEqual(command["executor"]["args"], ["commands/otc.py"])
        self.assertIn("im", command["entrypoints"])
        self.assertIn("web", command["entrypoints"])


if __name__ == "__main__":
    unittest.main()
