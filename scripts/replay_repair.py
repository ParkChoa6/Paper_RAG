"""离线回放 e2e_current_results.json：修前/修后的引用问题。

不调模型。把每一行的 materials 按 chunk_id 还原成 chunk 字典，
喂给 repair_indices，再看 verify 在修完之后还报几条。

用法: python scripts/replay_repair.py data/processed/e2e_current_results.json
（脚手架：只读历史结果 + chunks.json，不调模型、不写任何东西）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from paper_rag.cite import repair_indices, verify
from paper_rag.config import PROCESSED_DIR

results_path = Path(sys.argv[1])
data = json.loads(results_path.read_text(encoding="utf-8"))

chunks = json.loads((PROCESSED_DIR / "chunks.json").read_text(encoding="utf-8"))["chunks"]
by_id = {c["chunk_id"]: c for c in chunks}

tot_rows = tot_before = tot_fixed = tot_after = 0
new_problems = 0
detail = []

for arm, rows in data.items():
    for row in rows:
        if row["status"] != "answered":
            continue
        tot_rows += 1
        parsed = {"answer": row["answer"], "used": row["used"],
                  "quotes": row["quotes"]}
        mats = [by_id[m["chunk_id"]] for m in row["materials"]]

        before = verify(parsed, mats)
        fixed_parsed, repairs = repair_indices(parsed, mats)
        after = verify(fixed_parsed, mats)

        tot_before += len(before)
        tot_after += len(after)
        tot_fixed += len(repairs)
        added = set(after) - set(before)
        if added:
            new_problems += len(added)
            detail.append(f"!! 新增问题 {arm}#{row['n']}: {sorted(added)}")
        for r in repairs:
            detail.append(f"   修 {arm}#{row['n']}: {r}")

print(f"行数（answered）  {tot_rows}")
print(f"修前 引用问题      {tot_before} 处")
print(f"自动修正           {tot_fixed} 处")
print(f"修后 引用问题      {tot_after} 处")
print(f"★ 修完后新增问题   {new_problems} 例")
print("-" * 60)
for line in detail:
    print(line)
