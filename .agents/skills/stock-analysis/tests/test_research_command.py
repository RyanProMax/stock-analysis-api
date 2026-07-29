import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "commands"))

import research


class ResearchCommandTest(unittest.TestCase):
    def _make_fake_futu_preflight(self, root: pathlib.Path) -> tuple[pathlib.Path, dict[str, str]]:
        skill_dir = root / "stock-analysis-skill"
        api_root = root / "stock-analysis-api"
        futu_cli = api_root / "scripts" / "futu_market_data.py"
        uv_path = root / "tooling" / "uv"
        skill_dir.mkdir(parents=True)
        futu_cli.parent.mkdir(parents=True)
        uv_path.parent.mkdir(parents=True)
        futu_cli.write_text("#!/usr/bin/env python\n", encoding="utf-8")
        uv_path.write_text(
            '#!/bin/sh\necho \'{"data":{"qot_logined":true}}\'\n',
            encoding="utf-8",
        )
        uv_path.chmod(0o755)
        return skill_dir, {"HOME": str(root), "PATH": "", "STOCK_ANALYSIS_UV": str(uv_path)}

    def test_cn_symbol_builds_assistant_prompt_with_full_stock_analyze_cli(self) -> None:
        result = research.build_reply(
            {
                "argsText": "300750",
                "args": ["300750"],
                "workspace": {"name": "研究测试"},
            }
        )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertIn("stock-analysis-skill 的 /research", content)
        self.assertIn("当前工作区为：研究测试", content)
        self.assertIn("--market cn --symbols 300750 --mode full --pretty", content)
        self.assertIn("stock-analysis-api", content)
        self.assertIn("references/research.md", content)
        self.assertIn("A 股", content)
        self.assertIn("不输出买卖建议、本系统目标价", content)
        self.assertIn("机构目标价必须作为外部观点", content)

    def test_research_prompt_requires_quality_risk_and_validation_modules(self) -> None:
        result = research.build_reply({"argsText": "US.AAPL", "args": ["US.AAPL"]})

        content = result["reply"]["content"]

        self.assertIn("module_status", content)
        self.assertIn("source_freshness", content)
        self.assertIn("data_gaps", content)
        self.assertIn("风险与反证", content)
        self.assertIn("组合/持仓", content)
        self.assertIn("历史验证", content)
        self.assertIn("样本数", content)
        self.assertIn("不新增独立 /risk", content)

    def test_research_prompt_requires_industry_heat_peer_pe_and_institution_reports(self) -> None:
        result = research.build_reply({"argsText": "300750", "args": ["300750"]})

        content = result["reply"]["content"]

        self.assertIn("行业整体趋势", content)
        self.assertIn("市场热度", content)
        self.assertIn("同类公司平均 PE", content)
        self.assertIn("权威机构研报汇总", content)
        self.assertIn("研报发布日期", content)
        self.assertIn("机构目标价", content)
        self.assertIn("评级/观点", content)
        self.assertIn("不得把单一机构观点当成市场共识", content)

    def test_research_reference_defines_quality_risk_and_validation_contract(self) -> None:
        content = (ROOT / "references" / "research.md").read_text(encoding="utf-8")

        self.assertIn("module_status", content)
        self.assertIn("source_freshness", content)
        self.assertIn("data_gaps", content)
        self.assertIn("风险与反证", content)
        self.assertIn("组合/持仓风险", content)
        self.assertIn("历史验证", content)
        self.assertIn("只做历史统计", content)

    def test_research_reference_defines_industry_heat_peer_pe_and_institution_reports(self) -> None:
        content = (ROOT / "references" / "research.md").read_text(encoding="utf-8")

        self.assertIn("Industry Trend And Market Heat", content)
        self.assertIn("行业整体趋势", content)
        self.assertIn("市场热度", content)
        self.assertIn("同类公司平均 PE", content)
        self.assertIn("权威机构研报汇总", content)
        self.assertIn("研报发布日期", content)
        self.assertIn("机构目标价", content)
        self.assertIn("不得作为本系统建议", content)

    def test_research_prompt_requires_clean_final_and_feishu_short_form(self) -> None:
        result = research.build_reply(
            {"argsText": "300757", "args": ["300757"], "workspace": {"name": "飞书"}}
        )

        content = result["reply"]["content"]

        self.assertIn("最终回复必须直接从标题开始", content)
        self.assertIn("不得包含执行过程日志", content)
        self.assertIn("默认输出飞书短版", content)
        self.assertIn("2500-3500 字", content)
        self.assertIn("重点版 / 决策看板", content)
        self.assertIn("财务结构是否健康", content)
        self.assertIn("估值与行业相对位置", content)
        self.assertIn("机构观点综合", content)
        self.assertIn("调试细节", content)

    def test_research_reference_defines_final_reply_hygiene_and_short_form(self) -> None:
        content = (ROOT / "references" / "research.md").read_text(encoding="utf-8")

        self.assertIn("Final Reply Hygiene", content)
        self.assertIn("必须直接从标题开始", content)
        self.assertIn("不得包含执行过程日志", content)
        self.assertIn("Default Feishu Short Form", content)
        self.assertIn("2500-3500 字", content)
        self.assertIn("focus-first decision dashboard", content)
        self.assertIn("财务结构", content)
        self.assertIn("估值与行业相对位置", content)
        self.assertIn("机构观点综合", content)
        self.assertIn("Debug details", content)

    def test_cn_stock_name_passes_raw_input_to_upstream_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            api_root = root / "stock-analysis-api"
            script_path = api_root / "scripts" / "stock_analyze.py"
            skill_dir.mkdir()
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            result = research.build_reply(
                {"argsText": "宁德时代", "args": ["宁德时代"]},
                skill_dir=skill_dir,
                env={},
            )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertIn("--market cn --symbols", content)
        self.assertIn(research.shlex.quote("宁德时代"), content)
        self.assertIn("上游 CLI 负责股票名 / 公司名解析", content)
        self.assertNotIn("标的识别阶段", content)
        self.assertNotIn("<resolved_symbol>", content)

    def test_cn_stock_name_with_market_hint_passes_raw_input_to_upstream_cli(self) -> None:
        result = research.build_reply(
            {"argsText": "cn 宁德时代", "args": ["cn", "宁德时代"]},
            skill_dir=ROOT,
            env={},
        )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertIn("--market cn --symbols", content)
        self.assertIn(research.shlex.quote("宁德时代"), content)
        self.assertNotIn("A 股代码需要是 6 位数字", content)
        self.assertNotIn("标的识别阶段", content)

    def test_cn_prompt_uses_runtime_resolved_absolute_api_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "developer space" / "stock-analysis-skill"
            api_root = root / "developer space" / "stock-analysis-api"
            script_path = api_root / "scripts" / "stock_analyze.py"
            skill_dir.mkdir(parents=True)
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            result = research.build_reply(
                {
                    "argsText": "300750",
                    "args": ["300750"],
                    "workspace": {"name": "研究测试"},
                },
                skill_dir=skill_dir,
                env={},
            )

        content = result["reply"]["content"]

        self.assertIn(f"cd {research.shlex.quote(str(api_root))}", content)
        self.assertIn("uv run python scripts/stock_analyze.py", content)
        self.assertIn("--market cn --symbols 300750 --mode full --pretty", content)
        self.assertNotIn('cd "$STOCK_ANALYSIS_API_ROOT"', content)

    def test_cn_prompt_uses_runtime_resolved_absolute_uv_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            api_root = root / "stock-analysis-api"
            script_path = api_root / "scripts" / "stock_analyze.py"
            uv_path = root / "tooling" / "uv"
            skill_dir.mkdir()
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")

            result = research.build_reply(
                {"argsText": "300750", "args": ["300750"]},
                skill_dir=skill_dir,
                env={"STOCK_ANALYSIS_UV": str(uv_path)},
            )

        content = result["reply"]["content"]

        self.assertIn(f"{research.shlex.quote(str(uv_path))} run python", content)
        self.assertIn("scripts/stock_analyze.py", content)
        self.assertNotIn("&& uv run python", content)

    def test_api_root_without_uv_reports_preflight_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            api_root = root / "stock-analysis-api"
            script_path = api_root / "scripts" / "stock_analyze.py"
            skill_dir.mkdir()
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            result = research.build_reply(
                {"argsText": "300750", "args": ["300750"]},
                skill_dir=skill_dir,
                env={"PATH": "", "HOME": str(root / "empty-home")},
            )

        content = result["reply"]["content"]

        self.assertIn("未找到 uv 可执行文件", content)
        self.assertNotIn("scripts/stock_analyze.py --market cn", content)

    def test_env_api_root_takes_precedence_over_sibling_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            sibling_root = root / "stock-analysis-api"
            env_root = root / "env stock api"
            skill_dir.mkdir()
            for api_root in (sibling_root, env_root):
                script_path = api_root / "scripts" / "stock_analyze.py"
                script_path.parent.mkdir(parents=True)
                script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            result = research.build_reply(
                {"argsText": "US.AAPL", "args": ["US.AAPL"]},
                skill_dir=skill_dir,
                env={"STOCK_ANALYSIS_API_ROOT": str(env_root)},
            )

        content = result["reply"]["content"]

        self.assertIn(f"cd {research.shlex.quote(str(env_root))}", content)
        self.assertNotIn(f"cd {research.shlex.quote(str(sibling_root))}", content)

    def test_missing_api_root_reports_preflight_instead_of_relative_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            result = research.build_reply(
                {"argsText": "US.AAPL", "args": ["US.AAPL"]},
                skill_dir=skill_dir,
                env={},
            )

        content = result["reply"]["content"]

        self.assertIn("stock-analysis-api 预检：未找到", content)
        self.assertNotIn('cd "$STOCK_ANALYSIS_API_ROOT"', content)

    def test_empty_env_mapping_does_not_read_process_api_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            process_env_root = root / "process env api"
            script_path = process_env_root / "scripts" / "stock_analyze.py"
            skill_dir.mkdir()
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"STOCK_ANALYSIS_API_ROOT": str(process_env_root)},
            ):
                result = research.build_reply(
                    {"argsText": "300750", "args": ["300750"]},
                    skill_dir=skill_dir,
                    env={},
                )

        content = result["reply"]["content"]

        self.assertIn("stock-analysis-api 预检：未找到", content)
        self.assertNotIn(f"cd {research.shlex.quote(str(process_env_root))}", content)

    def test_api_root_resolution_does_not_guess_from_process_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "installed" / "stock-analysis-skill"
            cwd_api_root = root / "host workspace" / "stock-analysis-api"
            script_path = cwd_api_root / "scripts" / "stock_analyze.py"
            skill_dir.mkdir(parents=True)
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            with mock.patch.object(
                research.Path,
                "cwd",
                return_value=cwd_api_root.parent,
            ):
                result = research.build_reply(
                    {"argsText": "US.AAPL", "args": ["US.AAPL"]},
                    skill_dir=skill_dir,
                    env={},
                )

        content = result["reply"]["content"]

        self.assertIn("stock-analysis-api 预检：未找到", content)
        self.assertNotIn(f"cd {research.shlex.quote(str(cwd_api_root))}", content)

    def test_us_prefixed_symbol_builds_assistant_prompt_with_us_cli(self) -> None:
        result = research.build_reply(
            {
                "argsText": "US.AAPL",
                "args": ["US.AAPL"],
                "workspace": {"folder": "equity"},
            }
        )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertIn("当前工作区为：equity", content)
        self.assertIn("--market us --symbols AAPL --mode full --pretty", content)
        self.assertIn("美股", content)
        self.assertIn("SEC", content)
        self.assertIn("earnings transcript", content)

    def test_long_bare_english_company_name_is_not_forced_to_us_ticker(self) -> None:
        result = research.build_reply(
            {
                "argsText": "MINIMAX",
                "args": ["MINIMAX"],
                "workspace": {"name": "飞书研究"},
            }
        )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertIn("- 用户输入：`MINIMAX`", content)
        self.assertIn("- 识别市场：`待解析`", content)
        self.assertIn("- 标准代码：`MINIMAX`", content)
        self.assertIn("市场路由：待解析", content)
        self.assertIn("若唯一核验为港股", content)
        self.assertIn("不要把 `MINIMAX` 直接当作美股普通股代码", content)
        self.assertNotIn("--market us --symbols MINIMAX --mode full --pretty", content)
        self.assertNotIn("标题使用：`**/research｜US.MINIMAX", content)

    def test_exchange_prefixed_symbols_are_normalized(self) -> None:
        us_result = research.build_reply({"argsText": "NASDAQ:AAPL", "args": ["NASDAQ:AAPL"]})
        cn_result = research.build_reply({"argsText": "BJ.430047", "args": ["BJ.430047"]})

        self.assertIn(
            "--market us --symbols AAPL --mode full --pretty",
            us_result["reply"]["content"],
        )
        self.assertIn(
            "--market cn --symbols 430047 --mode full --pretty",
            cn_result["reply"]["content"],
        )

    def test_hk_research_without_opend_asks_before_degrading(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            result = research.build_reply(
                {"argsText": "HK.00700", "args": ["HK.00700"]},
                skill_dir=skill_dir,
                env={"HOME": str(root), "PATH": ""},
            )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "final_markdown")
        self.assertIn("OpenD 预检未通过", content)
        self.assertIn("是否继续", content)
        self.assertIn("/research HK.00700 --continue-without-opend", content)
        self.assertNotIn("assistant_prompt", json.dumps(result, ensure_ascii=False))

    def test_hk_research_confirmation_allows_degraded_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir = root / "stock-analysis-skill"
            skill_dir.mkdir()

            result = research.build_reply(
                {
                    "argsText": "HK.00700 --continue-without-opend",
                    "args": ["HK.00700", "--continue-without-opend"],
                },
                skill_dir=skill_dir,
                env={"HOME": str(root), "PATH": ""},
            )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertIn("用户已确认 OpenD 不可用时继续", content)
        self.assertIn("港股数据层降级", content)

    def test_hk_symbol_builds_assistant_prompt_with_hk_deferred_data_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            skill_dir, env = self._make_fake_futu_preflight(root)

            result = research.build_reply(
                {
                    "argsText": "HK.00700",
                    "args": ["HK.00700"],
                    "workspace": {"name": "港股研究"},
                },
                skill_dir=skill_dir,
                env=env,
            )

        reply = result["reply"]
        content = reply["content"]

        self.assertEqual(reply["type"], "assistant_prompt")
        self.assertIn("OpenD 预检已通过", content)
        self.assertIn("scripts/futu_market_data.py global-state --json", content)
        self.assertIn("HK.00700", content)
        self.assertIn("0700.HK", content)
        self.assertIn("港股", content)
        self.assertIn("后置支持", content)
        self.assertIn("stock-analysis-api Futu CLI", content)
        self.assertIn("HKEX", content)
        self.assertNotIn("uv run python scripts/stock_analyze.py --market hk", content)

    def test_main_hk_research_full_chain_uses_api_futu_cli_without_futuapi_skill(self) -> None:
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
            uv_path.write_text(
                '#!/bin/sh\necho \'{"status":"ok","source":"futu_opend","data":{"qot_logined":true}}\'\n',
                encoding="utf-8",
            )
            uv_path.chmod(0o755)
            env = {
                **os.environ,
                "AGENT_FABRIC_SKILL_DIR": str(skill_dir),
                "STOCK_ANALYSIS_API_ROOT": str(api_root),
                "STOCK_ANALYSIS_UV": str(uv_path),
            }

            proc = subprocess.run(
                [sys.executable, str(ROOT / "commands" / "research.py")],
                input=json.dumps(
                    {
                        "argsText": "HK.00700",
                        "args": ["HK.00700"],
                        "workspace": {"name": "链路验证"},
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )

        payload = json.loads(proc.stdout)
        content = payload["reply"]["content"]

        self.assertEqual(payload["reply"]["type"], "assistant_prompt")
        self.assertIn("OpenD 预检已通过", content)
        self.assertIn("scripts/futu_market_data.py global-state --json", content)
        self.assertIn("scripts/futu_market_data.py snapshot --codes HK.00700 --json", content)
        self.assertIn("scripts/futu_market_data.py kline --code HK.00700", content)
        self.assertIn(f"cd {research.shlex.quote(str(api_root))}", content)
        self.assertIn(str(uv_path), content)
        self.assertNotIn("futuapi", content.lower())
        self.assertNotIn("install-futu-opend", content)
        self.assertNotIn("外部 skill", content)

    def test_hk_research_opend_preflight_uses_isolated_runtime_dirs(self) -> None:
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
            uv_path.chmod(0o755)
            env = {
                "AGENT_FABRIC_SKILL_DIR": str(skill_dir),
                "STOCK_ANALYSIS_API_ROOT": str(api_root),
                "STOCK_ANALYSIS_UV": str(uv_path),
                "PATH": "",
            }

            with mock.patch.object(research.subprocess, "run") as run_mock:
                run_mock.return_value = subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout='{"status":"ok","data":{"qot_logined":true}}',
                    stderr="",
                )

                preflight = research.run_opend_preflight(skill_dir=skill_dir, env=env)

        self.assertTrue(preflight.ok)
        runtime_dir = research._opend_preflight_runtime_dir(api_root)
        run_env = run_mock.call_args.kwargs["env"]
        self.assertEqual(run_env["UV_CACHE_DIR"], str(runtime_dir / "uv-cache"))
        self.assertEqual(run_env["HOME"], str(runtime_dir / "home"))

    def test_hk_research_executor_limited_preflight_continues_to_agent_side_check(
        self,
    ) -> None:
        with mock.patch.object(
            research,
            "run_opend_preflight",
            return_value=research.OpenDPreflight(
                ok=False,
                reason="OpenD 预检超时（>8s）",
                command="cd /api && uv run python scripts/futu_market_data.py global-state --json",
            ),
        ):
            result = research.build_reply(
                {
                    "argsText": "HK.00700",
                    "args": ["HK.00700"],
                    "workspace": {"name": "沙箱验证"},
                }
            )

        content = result["reply"]["content"]

        self.assertEqual(result["reply"]["type"], "assistant_prompt")
        self.assertIn("OpenD 预检状态未知", content)
        self.assertIn("global-state --json", content)
        self.assertIn("snapshot --codes HK.00700 --json", content)
        self.assertNotIn("OpenD 预检未通过", content)

    def test_main_hk_research_loads_installed_skill_env_file(self) -> None:
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
            uv_path.write_text(
                '#!/bin/sh\necho \'{"status":"ok","source":"futu_opend","data":{"qot_logined":true}}\'\n',
                encoding="utf-8",
            )
            uv_path.chmod(0o755)
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
                [sys.executable, str(ROOT / "commands" / "research.py")],
                input=json.dumps(
                    {
                        "argsText": "HK.00700",
                        "args": ["HK.00700"],
                        "workspace": {"name": "安装副本验证"},
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )

        payload = json.loads(proc.stdout)
        content = payload["reply"]["content"]

        self.assertEqual(payload["reply"]["type"], "assistant_prompt")
        self.assertIn("OpenD 预检已通过", content)
        self.assertIn(f"cd {research.shlex.quote(str(api_root))}", content)
        self.assertIn(str(uv_path), content)
        self.assertIn("scripts/futu_market_data.py snapshot --codes HK.00700 --json", content)
        self.assertNotIn("OpenD 预检未通过", content)
        self.assertNotIn("futuapi", content.lower())

    def test_missing_symbol_returns_local_usage_markdown(self) -> None:
        result = research.build_reply({"argsText": "", "args": []})

        reply = result["reply"]

        self.assertEqual(reply["type"], "final_markdown")
        self.assertIn("/research <symbol>", reply["content"])
        self.assertIn("/research 300750", reply["content"])
        self.assertIn("/research US.AAPL", reply["content"])

    def test_multiple_symbols_are_rejected_locally(self) -> None:
        result = research.build_reply({"argsText": "300750 600519", "args": ["300750", "600519"]})

        reply = result["reply"]

        self.assertEqual(reply["type"], "final_markdown")
        self.assertIn("一次只支持一只股票", reply["content"])

    def test_shell_like_symbols_are_rejected_locally(self) -> None:
        dangerous_inputs = [
            ["AAPL;rm", "-rf", "/"],
            ["US.AAPL;rm"],
            ["US.AAPL$(touch pwned)"],
            ["US.AAPL`touch pwned`"],
        ]

        for args in dangerous_inputs:
            with self.subTest(args=args):
                result = research.build_reply({"argsText": " ".join(args), "args": args})

                self.assertEqual(result["reply"]["type"], "final_markdown")
                self.assertNotIn("assistant_prompt", json.dumps(result, ensure_ascii=False))

    def test_commands_json_registers_research(self) -> None:
        manifest = json.loads((ROOT / "commands.json").read_text(encoding="utf-8"))
        command = manifest["commands"]["research"]

        self.assertEqual(command["description"], "生成单只股票深度研报")
        self.assertEqual(command["entrypoints"], ["im", "web"])
        self.assertEqual(command["executor"]["command"], "python3")
        self.assertEqual(command["executor"]["args"], ["commands/research.py"])

    def test_main_emits_assistant_prompt_json(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "commands" / "research.py")],
            input=json.dumps(
                {
                    "argsText": "US.AAPL",
                    "args": ["US.AAPL"],
                    "workspace": {"name": "subprocess"},
                }
            ),
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(proc.stdout)

        self.assertEqual(payload["reply"]["type"], "assistant_prompt")
        self.assertIn("US.AAPL", payload["reply"]["content"])
        self.assertTrue(payload["reply"]["ack"])

    def test_main_uses_env_api_root_for_absolute_cli_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            api_root = pathlib.Path(raw_root).resolve() / "api root"
            script_path = api_root / "scripts" / "stock_analyze.py"
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            env = {**os.environ, "STOCK_ANALYSIS_API_ROOT": str(api_root)}

            proc = subprocess.run(
                [sys.executable, str(ROOT / "commands" / "research.py")],
                input=json.dumps({"argsText": "300750", "args": ["300750"]}),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )

        payload = json.loads(proc.stdout)

        self.assertIn(
            f"cd {research.shlex.quote(str(api_root))}",
            payload["reply"]["content"],
        )

    def test_main_uses_agent_fabric_skill_dir_for_sibling_api_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve() / "workspace root"
            skill_dir = root / "stock-analysis-skill"
            api_root = root / "stock-analysis-api"
            script_path = api_root / "scripts" / "stock_analyze.py"
            skill_dir.mkdir(parents=True)
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            env = dict(os.environ)
            env.pop("STOCK_ANALYSIS_API_ROOT", None)
            env["AGENT_FABRIC_SKILL_DIR"] = str(skill_dir)

            proc = subprocess.run(
                [sys.executable, str(ROOT / "commands" / "research.py")],
                input=json.dumps({"argsText": "US.AAPL", "args": ["US.AAPL"]}),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )

        payload = json.loads(proc.stdout)

        self.assertIn(
            f"cd {research.shlex.quote(str(api_root))}",
            payload["reply"]["content"],
        )
        self.assertIn(
            "--market us --symbols AAPL --mode full --pretty",
            payload["reply"]["content"],
        )

    def test_resolves_stock_analyze_from_monorepo_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            api_root = pathlib.Path(raw_root).resolve() / "stock-analysis-api"
            skill_dir = api_root / ".agents" / "skills" / "stock-analysis"
            script_path = api_root / "scripts" / "stock_analyze.py"
            uv_path = api_root / ".venv" / "bin" / "uv"
            skill_dir.mkdir(parents=True)
            script_path.parent.mkdir(parents=True)
            script_path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text("#!/bin/sh\n", encoding="utf-8")

            result = research.resolve_stock_analyze_command(
                research.ResearchTarget(
                    market="us",
                    input_symbol="AAPL",
                    normalized_symbol="AAPL",
                    display_symbol="AAPL",
                ),
                skill_dir=skill_dir,
                env={"STOCK_ANALYSIS_UV": str(uv_path)},
            )

        self.assertEqual(result.api_root, api_root)
        self.assertIn(f"cd {research.shlex.quote(str(api_root))}", result.command or "")
        self.assertIn("--market us --symbols AAPL --mode full --pretty", result.command or "")


if __name__ == "__main__":
    unittest.main()
