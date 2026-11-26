# -*- coding: utf-8 -*-
"""分块收集分支覆盖率：每块独立 pytest 进程，coverage 数据跨块合并。"""
import io
import subprocess
import sys

REPO = r"C:\Users\c30085341\projects\OpenAN\registry-center"
sys.path.insert(0, REPO)

# 1. 收集 file -> count
out = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "--co", "-q"],
    cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
counts = {}
for line in out.splitlines():
    line = line.strip()
    if "::" in line and line.startswith("tests/"):
        path = line.split("::")[0]
        counts[path] = counts.get(path, 0) + 1
    elif line.startswith("tests/") and ".py: " in line and \
            line.rsplit(": ", 1)[1].isdigit():
        path, num = line.rsplit(": ", 1)
        path = path.replace("\\", "/")
        counts[path] = counts.get(path, 0) + int(num)

# 2. 排序打包（cli 先，其余按字母序），每块 <= 480
ordered = sorted(counts)
ordered = [f for f in ordered if not f.startswith("tests/cli/")] + \
          [f for f in sorted(counts) if f.startswith("tests/cli/")]
chunks, cur, cur_n = [], [], 0
for f in ordered:
    n = counts.get(f, 0)
    if cur_n > 0 and cur_n + n > 480:
        chunks.append(cur)
        cur, cur_n = [], 0
    cur.append(f)
    cur_n += n
if cur_n:
    chunks.append(cur)
print(f"total tests={sum(counts.values())}, files={len(counts)}, chunks={len(chunks)}")

# 3. 逐块 coverage run --branch --append（崩溃重试一次）
import os
env = dict(os.environ)
for i, chunk in enumerate(chunks, 1):
    ok = False
    attempt = 0
    while attempt < 2 and not ok:
        attempt += 1
        r = subprocess.run(
            [sys.executable, "-m", "coverage", "run", "--branch", "--append",
             "-m", "pytest", *chunk, "-q", "--no-header"],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900, env=env)
        tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        print(f"chunk {i}/{len(chunks)} attempt {attempt}: exit={r.returncode} | {tail[-90:]}")
        ok = r.returncode in (0, 1, 5)
print("coverage collection complete")
