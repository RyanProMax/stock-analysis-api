"""
缓存工具模块

提供缓存功能，支持本地文件系统
- 股票列表缓存：cache/stock_list/
- 分析报告缓存：cache/reports/
- 盯盘基线缓存：cache/watch/
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, Dict, List


class CacheUtil:
    """缓存工具类"""

    @staticmethod
    def get_cst_date_key() -> str:
        """
        获取中国标准时间的日期键（YYYY-MM-DD）

        缓存刷新规则：
        - 中国标准时间（UTC+8）早上6点后刷新缓存
        - 早上6点前仍使用前一天的日期

        Returns:
            str: 日期字符串，格式为 YYYY-MM-DD
        """
        # 获取中国标准时间 (UTC+8)
        cst_tz = timezone(timedelta(hours=8))
        now_cst = datetime.now(cst_tz)

        # 如果当前时间早于早上6点，使用前一天的日期
        # 这样确保缓存只在早上6点后更新
        if now_cst.hour < 6:
            now_cst -= timedelta(days=1)

        return now_cst.strftime("%Y-%m-%d")

    # 本地文件系统缓存根目录
    _cache_root = os.environ.get("CACHE_DIR")
    if _cache_root:
        CACHE_ROOT = Path(_cache_root)
    else:
        # 默认使用当前工作目录下的 .cache/ 目录
        CACHE_ROOT = Path(".cache")

    STOCK_LIST_CACHE_DIR = "stock_list"
    REPORTS_CACHE_DIR = "reports"
    WATCH_CACHE_DIR = "watch"

    @classmethod
    def _ensure_cache_dir(cls, cache_dir: Path) -> None:
        """确保本地缓存目录存在"""
        cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _get_local_cache_file_path(cls, cache_dir: str, filename: str) -> Path:
        """获取本地缓存文件路径"""
        local_dir = cls.CACHE_ROOT / cache_dir
        cls._ensure_cache_dir(local_dir)
        return local_dir / filename

    @classmethod
    def save_stock_list(
        cls,
        market: str,
        data: List[Dict[str, Any]],
        date: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """
        保存股票列表到本地文件系统缓存

        Args:
            market: 市场类型（"A股" 或 "美股"）
            data: 股票列表数据
            date: 日期（YYYY-MM-DD），如果为 None 则使用今天
            force: 是否强制覆盖已存在的缓存，默认 False

        Returns:
            bool: 是否保存成功
        """
        try:
            if date is None:
                date = cls.get_cst_date_key()

            # 文件名：a_stocks_YYYY-MM-DD.json 或 us_stocks_YYYY-MM-DD.json
            market_prefix = "a_stocks" if market == "A股" else "us_stocks"
            filename = f"{market_prefix}_{date}.json"

            # 保存到本地文件系统
            cache_file = cls._get_local_cache_file_path(cls.STOCK_LIST_CACHE_DIR, filename)
            if not force and cache_file.exists():
                return True
            else:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"✓ 股票列表已保存到本地缓存: {cache_file}")
                return True
        except Exception as e:
            print(f"⚠️ 保存股票列表缓存失败: {e}")
            return False

    @classmethod
    def load_stock_list(
        cls, market: str, date: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        从本地文件系统缓存加载股票列表

        Args:
            market: 市场类型（"A股" 或 "美股"）
            date: 日期（YYYY-MM-DD），如果为 None 则使用今天

        Returns:
            Optional[List[Dict[str, Any]]]: 股票列表数据，如果不存在则返回 None
        """
        try:
            if date is None:
                date = cls.get_cst_date_key()

            market_prefix = "a_stocks" if market == "A股" else "us_stocks"
            filename = f"{market_prefix}_{date}.json"

            # 从本地文件系统加载
            cache_file = cls._get_local_cache_file_path(cls.STOCK_LIST_CACHE_DIR, filename)
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, list) and len(data) > 0:
                    print(f"✓ 从本地缓存加载股票列表: {cache_file}，共 {len(data)} 只股票")
                    return data
                else:
                    print(f"⚠️ 缓存文件存在但数据为空: {cache_file}")

            return None
        except Exception as e:
            print(f"⚠️ 加载股票列表缓存失败: {e}")
            return None

    @classmethod
    def save_report(
        cls,
        symbol: str,
        report: Dict[str, Any],
        date: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """
        保存分析报告到本地文件系统缓存

        Args:
            symbol: 股票代码
            report: 分析报告数据（字典格式）
            date: 日期（YYYY-MM-DD），如果为 None 则使用今天
            force: 是否强制覆盖已存在的缓存，默认 False

        Returns:
            bool: 是否保存成功
        """
        try:
            if date is None:
                date = cls.get_cst_date_key()

            filename = f"{symbol.upper()}.json"

            # 保存到本地文件系统
            date_dir = cls.CACHE_ROOT / cls.REPORTS_CACHE_DIR / date
            cls._ensure_cache_dir(date_dir)
            cache_file = date_dir / filename

            # 如果本地文件已存在且不强制覆盖，则跳过保存
            if not force and cache_file.exists():
                return True
            else:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                print(f"✓ 分析报告已保存到本地缓存: {cache_file}")
                return True
        except Exception as e:
            print(f"⚠️ 保存分析报告缓存失败: {e}")
            return False

    @classmethod
    def load_report(cls, symbol: str, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        从本地文件系统缓存加载分析报告

        Args:
            symbol: 股票代码
            date: 日期（YYYY-MM-DD），如果为 None 则使用今天

        Returns:
            Optional[Dict[str, Any]]: 分析报告数据，如果不存在则返回 None
        """
        try:
            if date is None:
                date = cls.get_cst_date_key()

            filename = f"{symbol.upper()}.json"

            # 从本地文件系统加载
            date_dir = cls.CACHE_ROOT / cls.REPORTS_CACHE_DIR / date
            cache_file = date_dir / filename

            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"✓ 从本地缓存加载分析报告: {cache_file}")
                return data

            return None
        except Exception as e:
            print(f"⚠️ 加载分析报告缓存失败: {e}")
            return None

    @classmethod
    def save_watch_baseline(cls, symbol: str, payload: Dict[str, Any]) -> bool:
        try:
            filename = f"{symbol.upper()}.json"
            cache_file = cls._get_local_cache_file_path(cls.WATCH_CACHE_DIR, filename)
            wrapped = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(wrapped, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"⚠️ 保存盯盘基线缓存失败: {e}")
            return False

    @classmethod
    def load_watch_baseline(
        cls,
        symbol: str,
        ttl_hours: int = 24,
    ) -> Optional[Dict[str, Any]]:
        try:
            filename = f"{symbol.upper()}.json"
            cache_file = cls._get_local_cache_file_path(cls.WATCH_CACHE_DIR, filename)
            if not cache_file.exists():
                return None

            with open(cache_file, "r", encoding="utf-8") as f:
                wrapped = json.load(f)

            if not isinstance(wrapped, dict):
                return None

            saved_at_raw = wrapped.get("saved_at")
            payload = wrapped.get("payload")
            if not saved_at_raw or not isinstance(payload, dict):
                return None

            saved_at = datetime.fromisoformat(str(saved_at_raw))
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=timezone.utc)

            age = datetime.now(timezone.utc) - saved_at.astimezone(timezone.utc)
            if age > timedelta(hours=ttl_hours):
                return None

            return payload
        except Exception as e:
            print(f"⚠️ 加载盯盘基线缓存失败: {e}")
            return None

    @classmethod
    def cleanup_old_cache(cls, days_to_keep: int = 7) -> None:
        """
        清理旧的缓存文件（保留最近 N 天的缓存）

        Args:
            days_to_keep: 保留最近几天的缓存，默认 7 天
        """
        try:
            today = datetime.now()

            # 清理本地股票列表缓存
            local_stock_dir = cls.CACHE_ROOT / cls.STOCK_LIST_CACHE_DIR
            if local_stock_dir.exists():
                for cache_file in local_stock_dir.glob("*.json"):
                    try:
                        # 从文件名提取日期：a_stocks_YYYY-MM-DD.json
                        date_str = cache_file.stem.split("_")[-1]
                        file_date = datetime.strptime(date_str, "%Y-%m-%d")
                        days_diff = (today - file_date).days

                        if days_diff > days_to_keep:
                            cache_file.unlink()
                            print(f"✓ 已删除旧缓存: {cache_file}")
                    except Exception:
                        continue

            # 清理本地分析报告缓存
            local_reports_dir = cls.CACHE_ROOT / cls.REPORTS_CACHE_DIR
            if local_reports_dir.exists():
                for date_dir in local_reports_dir.iterdir():
                    if not date_dir.is_dir():
                        continue

                    try:
                        date_str = date_dir.name
                        file_date = datetime.strptime(date_str, "%Y-%m-%d")
                        days_diff = (today - file_date).days

                        if days_diff > days_to_keep:
                            import shutil

                            shutil.rmtree(date_dir)
                            print(f"✓ 已删除旧缓存目录: {date_dir}")
                    except Exception:
                        continue

        except Exception as e:
            print(f"⚠️ 清理旧缓存失败: {e}")
