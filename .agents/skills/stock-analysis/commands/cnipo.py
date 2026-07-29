#!/usr/bin/env python3
"""Skill command executor for /cnipo."""

from __future__ import annotations

import json
import sys

payload = {
    "reply": {
        "type": "final_markdown",
        "content": "## /cnipo\n\n已预留命令位，A 股 IPO 自动发现与分析暂未实现；后续会按与 /hkipo 相同的结构化模板扩展。",
    }
}

sys.stdout.write(json.dumps(payload, ensure_ascii=False))
