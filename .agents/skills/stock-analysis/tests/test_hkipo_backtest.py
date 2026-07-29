import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hkipo_backtest import (
    IpoSample,
    apply_futu_debut_returns,
    apply_xinguyufu_enrichment,
    make_futu_debut_close_fetcher,
    resolve_futu_api_root,
    summarize_score_calibration,
)


def make_sample(code: str, odds_score: int, debut_return_pct: float) -> IpoSample:
    return IpoSample(
        name=f"Sample {code}",
        code=code,
        listing_date="2026/01/01",
        market_cap_text="N/A",
        market_cap_mid_hkd_b=None,
        industry="other",
        offer_price=None,
        listing_price=None,
        oversub_rate=None,
        applied_lots_for_one_lot=None,
        one_lot_success_rate=None,
        last_price=None,
        debut_return_pct=debut_return_pct,
        accumulated_return_pct=None,
        heat_bucket="unknown",
        valuation_bucket="unknown",
        grey_market_return_pct=None,
        greenshoe=None,
        cornerstone=None,
        heat_score=None,
        industry_score=None,
        valuation_score=None,
        structure_score=None,
        grey_score=None,
        odds_score=odds_score,
    )


class ScoreCalibrationTest(unittest.TestCase):
    def test_summarizes_score_buckets_and_mismatches(self) -> None:
        samples = [
            make_sample("00001.HK", 95, 120.0),
            make_sample("00002.HK", 86, -8.0),
            make_sample("00003.HK", 70, 12.0),
            make_sample("00004.HK", 55, -15.0),
            make_sample("00005.HK", 45, 80.0),
        ]

        calibration = summarize_score_calibration(samples)

        self.assertEqual(
            [row["bucket"] for row in calibration["by_score_bucket"]],
            ["90-100", "80-89", "65-79", "50-64", "<50"],
        )
        self.assertEqual(calibration["by_score_bucket"][0]["count"], 1)
        self.assertEqual(calibration["by_score_bucket"][0]["win_rate"], 1.0)
        self.assertEqual(calibration["by_score_bucket"][1]["break_rate"], 1.0)
        self.assertGreater(calibration["score_return_rank_correlation"], 0)
        mismatch_codes = {row["code"] for row in calibration["mismatch_samples"]}
        self.assertIn("00002.HK", mismatch_codes)
        self.assertIn("00005.HK", mismatch_codes)


class FutuDebutReturnTest(unittest.TestCase):
    def test_resolves_futu_api_root_from_integrated_skill_directory(self) -> None:
        self.assertEqual(resolve_futu_api_root(env={}), ROOT.parents[2])

    def test_applies_futu_first_day_close_to_debut_return(self) -> None:
        sample = make_sample("02635.HK", 62, 10.0)
        sample.listing_date = "2025/12/23"
        sample.offer_price = 80.0

        updated = apply_futu_debut_returns([sample], fetch_close=lambda code, date: 100.0)

        self.assertEqual(updated, 1)
        self.assertEqual(sample.debut_return_source, "futu_kline")
        self.assertEqual(sample.futu_debut_close, 100.0)
        self.assertEqual(sample.listed_table_debut_return_pct, 10.0)
        self.assertAlmostEqual(sample.debut_return_pct, 25.0)

    def test_futu_first_day_close_fetcher_uses_stock_analysis_api_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root).resolve()
            api_root = root / "stock-analysis-api"
            futu_cli = api_root / "scripts" / "futu_market_data.py"
            uv_path = root / "tooling" / "uv"
            futu_cli.parent.mkdir(parents=True)
            futu_cli.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            uv_path.parent.mkdir(parents=True)
            uv_path.write_text(
                "#!/bin/sh\n"
                'printf \'%s\n\' \'{"status":"ok","data":[{"time_key":"2025-12-23","close":88.8}]}\'\n',
                encoding="utf-8",
            )
            uv_path.chmod(0o755)

            fetch_close, closer = make_futu_debut_close_fetcher(
                api_root=api_root,
                uv_path=uv_path,
            )
            close = fetch_close("02635.HK", "2025-12-23")
            closer.close()

        self.assertEqual(close, 88.8)


class XinguyufuEnrichmentTest(unittest.TestCase):
    def test_applies_xinguyufu_structure_and_grey_market_fields(self) -> None:
        sample = make_sample("02589.HK", 80, 40.0)
        rows = {
            "02589": {
                "暗盘涨幅_百分比": 62.04,
                "富途暗盘_百分比": 61.5,
                "绿鞋公开_百分比": 30.0,
                "基石": "有",
                "保荐人": "东方融资(香港)",
                "稳价人": "中信里昂证券",
                "回拨比例_百分比": 50.0,
                "行业": "食品饮料",
            }
        }

        updated = apply_xinguyufu_enrichment([sample], fetch_row=lambda code: rows.get(code))

        self.assertEqual(updated, 1)
        self.assertEqual(sample.enrichment_source, "xinguyufu")
        self.assertEqual(sample.greenshoe, "yes")
        self.assertEqual(sample.cornerstone, "yes")
        self.assertEqual(sample.grey_market_return_pct, 62.04)
        self.assertEqual(sample.futu_grey_market_return_pct, 61.5)
        self.assertEqual(sample.sponsor, "东方融资(香港)")
        self.assertEqual(sample.stabilizer, "中信里昂证券")
        self.assertEqual(sample.clawback_pct, 50.0)
        self.assertEqual(sample.industry, "食品饮料")


if __name__ == "__main__":
    unittest.main()
