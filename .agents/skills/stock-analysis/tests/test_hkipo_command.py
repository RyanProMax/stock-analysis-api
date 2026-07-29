import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "commands"))

import hkipo


class HkipoFutuCommandTest(unittest.TestCase):
    def test_main_emits_workflow_trigger_with_all_flag(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "commands" / "hkipo.py")],
            input=json.dumps(
                {
                    "argsText": "--all",
                    "args": ["--all"],
                    "workspace": {"name": "链路验证"},
                }
            ),
            text=True,
            capture_output=True,
            check=True,
        )

        payload = json.loads(proc.stdout)

        self.assertEqual(payload["reply"]["type"], "workflow")
        self.assertEqual(payload["reply"]["workflowId"], "hkipo")
        self.assertEqual(payload["reply"]["prompt"], "港股 IPO 打新分析")
        self.assertEqual(
            payload["reply"]["input"],
            {
                "command": "hkipo",
                "includeClosed": True,
                "argsText": "--all",
            },
        )
        self.assertIn("港股 IPO 工作流", payload["reply"]["ack"])

    def test_prompt_excludes_closed_ipo_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            prompt = hkipo.build_prompt(
                {
                    "argsText": "",
                    "args": [],
                    "workspace": {"name": "测试工作区"},
                },
                skill_dir=skill_dir,
                home_dir=root,
            )

        self.assertIn("默认只输出当前仍可认购的港股 IPO", prompt)
        self.assertIn("过滤 `is_subscribe_status=false`", prompt)
        self.assertIn("/hkipo --all", prompt)
        self.assertNotIn("--include" + "-closed", prompt)
        self.assertNotIn("自动发现当前“可认购”或“已截止认购但未上市”", prompt)

    def test_prompt_can_include_closed_ipo_with_all_flag(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            prompt = hkipo.build_prompt(
                {
                    "argsText": "--all",
                    "args": ["--all"],
                    "workspace": {"name": "测试工作区"},
                },
                skill_dir=skill_dir,
                home_dir=root,
            )

        self.assertIn("输出当前仍可认购 + 已截止认购但未上市的港股 IPO", prompt)
        self.assertIn("用户已显式传入 `--all`", prompt)
        self.assertIn("保留 `is_subscribe_status=false` 且上市日未到的标的", prompt)
        self.assertNotIn("--include" + "-closed", prompt)

    def test_prompt_removes_subscription_conflict_section_and_uses_dates_in_rank_title(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=root,
            )

        self.assertIn("个股标题末尾必须写申购截止日和开奖/配发结果日", prompt)
        self.assertIn("5/6截止 | 5/7开奖", prompt)
        self.assertIn("**🟢 1｜代码 公司｜评分｜M/D截止 | M/D开奖**", prompt)
        self.assertNotIn("**⏱ 申购冲突**", prompt)
        self.assertNotIn("申购冲突：", prompt)
        self.assertNotIn("同批次资金冲突", prompt)
        self.assertNotIn("高优先级跟踪", prompt)
        self.assertNotIn("重点跟踪", prompt)
        self.assertNotIn("投资建议", prompt)

    def test_prompt_uses_compact_report_body_without_blank_empty_lines(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=root,
            )

        self.assertIn("**💡 关键结论**\n- 🟢", prompt)
        self.assertIn("**📌 优先级**\n**🟢 1", prompt)
        self.assertIn("⚠️ 风险：一句话最大风险\n**🔗 来源**", prompt)
        self.assertIn(
            "正文不要插入空白空行；顶层小节标题、bullet、个股标题和个股字段都用单换行连续排列",
            prompt,
        )
        self.assertIn("📍 阶段：招股/截止/暗盘/上市日", prompt)
        self.assertIn("\n💰 热度：最新孖展/公开认购/暗盘", prompt)
        self.assertNotIn("\n\n**💡 关键结论**", prompt)
        self.assertNotIn("\n\n**📌 优先级**", prompt)
        self.assertNotIn("\n\n**🔗 来源**", prompt)
        self.assertNotIn("\n\n💰 热度：最新孖展/公开认购/暗盘", prompt)
        self.assertNotIn("\n\n🛡 结构：绿鞋/基石/保荐/回拨", prompt)
        self.assertNotIn("\n\n📈 回测：对应热度分桶", prompt)
        self.assertNotIn("每条 emoji 字段上方都保留一个空行", prompt)
        self.assertIn("报告正文", prompt)
        self.assertNotIn("飞书卡片", prompt)
        self.assertNotIn("thinking", prompt.lower())
        self.assertNotIn("tool steps", prompt.lower())

    def test_prompt_requires_same_day_heat_retry_and_multi_source_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=root,
            )

        self.assertIn("开放认购中的 IPO 热度必须通过当日硬门槛", prompt)
        self.assertIn("至少检索 3 类权威来源", prompt)
        self.assertIn("自动重试", prompt)
        self.assertIn("券商新股中心", prompt)
        self.assertIn("财经门户新股频道", prompt)
        self.assertIn("不得把前一日或更旧孖展倍率用于主评分", prompt)
        self.assertIn("热度未达当日核验门槛", prompt)
        self.assertNotIn("当日或最接近报告日的券商/财经站孖展统计", prompt)

    def test_prompt_requires_multi_institution_latest_heat_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=root,
            )

        self.assertIn("Futu CLI 不暴露 App 新股热度", prompt)
        self.assertIn("不得把单一券商孖展下限当作全市场主热度", prompt)
        self.assertIn("优先取同日多券商汇总", prompt)
        self.assertIn("Futu/牛牛", prompt)
        self.assertIn("TradeGo", prompt)
        self.assertIn("华盛", prompt)
        self.assertIn("老虎", prompt)
        self.assertIn("AAStocks", prompt)
        self.assertIn("ETNet", prompt)

    def test_reference_uses_compact_sections_and_date_title_contract(self) -> None:
        reference = (ROOT / "references" / "hkipo.md").read_text(encoding="utf-8")

        self.assertIn("deadline and allotment/result date", reference)
        self.assertIn("**🟢 1｜代码 公司｜评分｜M/D截止 | M/D开奖**", reference)
        self.assertIn("Do not insert blank empty lines", reference)
        self.assertIn("fixed source order", reference)
        self.assertNotIn("**⏱ 申购冲突**", reference)
        self.assertNotIn("⏱ 申购冲突：", reference)
        self.assertNotIn("each emoji field", reference)
        self.assertNotIn("inside every IPO block", reference)
        self.assertNotIn("thinking", reference.lower())
        self.assertNotIn("tool steps", reference.lower())

    def test_reference_requires_same_day_heat_gate(self) -> None:
        reference = (ROOT / "references" / "hkipo.md").read_text(encoding="utf-8")

        self.assertIn("same-day hard gate", reference)
        self.assertIn("at least three authoritative source families", reference)
        self.assertIn("do not score previous-day or older margin data", reference)
        self.assertIn("热度未达当日核验门槛", reference)
        self.assertNotIn("updated on or closest before the report date", reference)

    def test_reference_requires_latest_multi_source_aggregation(self) -> None:
        reference = (ROOT / "references" / "hkipo.md").read_text(encoding="utf-8")

        self.assertIn("Latest Heat Aggregation", reference)
        self.assertIn("Futu App / Niuniu", reference)
        self.assertIn("TradeGo", reference)
        self.assertIn("single-broker lower bound", reference)
        self.assertIn("must not be treated as market-wide heat", reference)
        self.assertIn("prefer same-day multi-broker aggregate sources", reference)

    def test_prompt_uses_runtime_resolved_stock_analysis_api_futu_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "developer space" / "stock-analysis-skill"
            api_root = root / "developer space" / "stock-analysis-api"
            futu_cli = api_root / "scripts" / "futu_market_data.py"
            uv_path = root / "tooling" / "uv"
            skill_dir.mkdir(parents=True)
            futu_cli.parent.mkdir(parents=True)
            futu_cli.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=root,
                env={"STOCK_ANALYSIS_UV": str(uv_path)},
            )

        self.assertIn(f"cd {hkipo.shlex.quote(str(api_root))}", prompt)
        self.assertIn(str(uv_path), prompt)
        self.assertIn("scripts/futu_market_data.py ipo-list --market HK --json", prompt)
        self.assertNotIn("futuapi", prompt)
        self.assertNotIn("`.venv/bin/python ", prompt)
        self.assertNotIn("/Users/ryan", prompt)

    def test_main_emits_workflow_trigger_without_futuapi_skill(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            api_root = root / "stock-analysis-api"
            futu_cli = api_root / "scripts" / "futu_market_data.py"
            uv_path = root / "tooling" / "uv"
            skill_dir.mkdir(parents=True)
            futu_cli.parent.mkdir(parents=True)
            futu_cli.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")
            env = {
                **os.environ,
                "AGENT_FABRIC_SKILL_DIR": str(skill_dir),
                "STOCK_ANALYSIS_API_ROOT": str(api_root),
                "STOCK_ANALYSIS_UV": str(uv_path),
            }

            proc = subprocess.run(
                [sys.executable, str(ROOT / "commands" / "hkipo.py")],
                input=json.dumps(
                    {
                        "argsText": "",
                        "args": [],
                        "workspace": {"name": "链路验证"},
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )

        payload = json.loads(proc.stdout)

        self.assertEqual(payload["reply"]["type"], "workflow")
        self.assertEqual(payload["reply"]["workflowId"], "hkipo")
        self.assertEqual(payload["reply"]["prompt"], "港股 IPO 打新分析")
        self.assertFalse(payload["reply"]["input"]["includeClosed"])
        self.assertNotIn("assistant_prompt", proc.stdout)
        self.assertNotIn("futuapi", proc.stdout.lower())
        self.assertNotIn("install-futu-opend", proc.stdout)
        self.assertNotIn("外部 skill 脚本", proc.stdout)

    def test_main_loads_installed_skill_env_file_for_api_futu_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "installed" / "stock-analysis-skill"
            api_root = root / "api root"
            futu_cli = api_root / "scripts" / "futu_market_data.py"
            uv_path = root / "tooling" / "uv"
            skill_dir.mkdir(parents=True)
            futu_cli.parent.mkdir(parents=True)
            futu_cli.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")
            (skill_dir / ".env").write_text(
                f'STOCK_ANALYSIS_API_ROOT="{api_root}"\n' f'STOCK_ANALYSIS_UV="{uv_path}"\n',
                encoding="utf-8",
            )

            env = dict(os.environ)
            for key in ("STOCK_ANALYSIS_API_ROOT", "STOCK_ANALYSIS_UV", "UV_BIN", "UV"):
                env.pop(key, None)
            env["AGENT_FABRIC_SKILL_DIR"] = str(skill_dir)
            env["PATH"] = ""

            proc = subprocess.run(
                [sys.executable, str(ROOT / "commands" / "hkipo.py")],
                input=json.dumps({"argsText": "", "args": []}),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )

        payload = json.loads(proc.stdout)

        self.assertEqual(payload["reply"]["type"], "workflow")
        self.assertEqual(payload["reply"]["workflowId"], "hkipo")
        self.assertEqual(payload["reply"]["prompt"], "港股 IPO 打新分析")
        self.assertFalse(payload["reply"]["input"]["includeClosed"])
        self.assertNotIn("assistant_prompt", proc.stdout)
        self.assertNotIn("stock-analysis-api Futu CLI 预检：未找到", proc.stdout)

    def test_prompt_reports_missing_futu_preflight_without_relative_venv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=root,
            )

        self.assertIn("stock-analysis-api Futu CLI 预检：未找到", prompt)
        self.assertNotIn("`.venv/bin/python ", prompt)
        self.assertNotIn("/Users/ryan", prompt)

    def test_prompt_can_use_sibling_api_root_when_env_root_is_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            api_root = root / "stock-analysis-api"
            futu_cli = api_root / "scripts" / "futu_market_data.py"
            uv_path = root / "uv"
            skill_dir.mkdir(parents=True)
            futu_cli.parent.mkdir(parents=True)
            futu_cli.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=root,
                env={"STOCK_ANALYSIS_UV": str(uv_path)},
            )

        self.assertIn("scripts/futu_market_data.py ipo-list --market HK --json", prompt)
        self.assertNotIn("stock-analysis-api Futu CLI 预检：未找到", prompt)

    def test_prompt_discovers_monorepo_api_root_without_api_env(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            api_root = pathlib.Path(raw_root).resolve() / "stock-analysis-api"
            skill_dir = api_root / ".agents" / "skills" / "stock-analysis"
            futu_cli = api_root / "scripts" / "futu_market_data.py"
            uv_path = api_root / ".venv" / "bin" / "uv"
            skill_dir.mkdir(parents=True)
            futu_cli.parent.mkdir(parents=True)
            futu_cli.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")

            prompt = hkipo.build_prompt(
                {"workspace": {"name": "测试工作区"}},
                skill_dir=skill_dir,
                home_dir=api_root.parent,
                env={"STOCK_ANALYSIS_UV": str(uv_path)},
            )

        self.assertIn(f"cd {hkipo.shlex.quote(str(api_root))}", prompt)
        self.assertIn("scripts/futu_market_data.py ipo-list --market HK --json", prompt)
        self.assertNotIn("stock-analysis-api Futu CLI 预检：未找到", prompt)


if __name__ == "__main__":
    unittest.main()
