# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Windows test runner for registry-center.
#
# Why this exists: on the corporate Windows Python 3.11.9 build, a single pytest
# process becomes unstable after roughly 700 tests when test files spawn child
# processes (Git bash entrypoint probes, isolated uvicorn services): the runner
# exits silently with code 1 (no traceback, no WER event, no faulthandler dump).
# The same tests pass reliably when grouped into smaller pytest processes.
#
# This script splits the suite into chunks of <= $ChunkSize tests (whole files,
# so intra-file fixtures stay in one process), runs each chunk in its own
# pytest process, retries a crashed chunk once, and aggregates the results.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_tests_windows.ps1 [-ChunkSize 500]

param(
    [int]$ChunkSize = 500,
    [string]$PytestArgs = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# --- 1. Collect file -> test-count mapping (imports all modules once) -------
$collect = & python -m pytest tests/ --co -q 2>&1 | Where-Object { $_ -match '^tests[/\\]\S+\.py' }
$map = @{}
foreach ($line in $collect) {
    # compact format: "tests\cli\test_base.py: 23" (file: count)
    if ($line -match '^(tests[/\\]\S+\.py):\s+(\d+)$') {
        $file = $Matches[1] -replace '/', '\'
        if (-not $map.ContainsKey($file)) { $map[$file] = 0 }
        $map[$file] += [int]$Matches[2]
    }
    # node-id format: "tests\cli\test_base.py::test_x"
    elseif ($line -match '^(tests[/\\]\S+\.py)::') {
        $file = $Matches[1] -replace '/', '\'
        if (-not $map.ContainsKey($file)) { $map[$file] = 0 }
        $map[$file]++
    }
}
$totalTests = ($map.Values | Measure-Object -Sum).Sum
Write-Host ("Collected {0} tests in {1} files" -f $totalTests, $map.Count)

# --- 2. Greedy-pack whole files into chunks (keep tests/cli first, like CI) --
$ordered = @()
$ordered += Get-ChildItem tests\cli -Filter test_*.py | ForEach-Object { $_.FullName }
$ordered += Get-ChildItem tests -Filter test_*.py | ForEach-Object { $_.FullName }
$ordered = $ordered | Select-Object -Unique | ForEach-Object {
    $_.Replace($repo + '\', '').Replace($repo + '/', '')
}
Write-Host ("Debug: ordered candidate files = {0}" -f $ordered.Count)

$chunks = @()
$current = @(); $currentCount = 0
foreach ($file in $ordered) {
    $count = 0
    if ($map.ContainsKey($file)) { $count = $map[$file] }
    if ($currentCount -gt 0 -and ($currentCount + $count) -gt $ChunkSize) {
        $chunks += ,@($current)
        $current = @(); $currentCount = 0
    }
    $current += $file
    $currentCount += $count
}
if ($currentCount -gt 0) { $chunks += ,@($current) }
Write-Host ("Split into {0} chunks" -f $chunks.Count)

# --- 3. Run each chunk in its own pytest process (one retry on crash) -------
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportDir = Join-Path $repo "log\test_reports\$stamp"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

$grandPassed = 0; $grandSkipped = 0; $grandFailed = 0; $grandErrors = 0
$chunkIndex = 0
foreach ($chunk in $chunks) {
    $chunkIndex++
    $count = 0
    foreach ($file in $chunk) { if ($map.ContainsKey($file)) { $count += $map[$file] } }
    Write-Host ("`n=== Chunk {0}/{1}: {2} tests in {3} files ===" -f $chunkIndex, $chunks.Count, $count, $chunk.Count)
    foreach ($file in $chunk) { Write-Host ("  " + $file) }

    $attempt = 0
    $ok = $false
    while ($attempt -lt 2 -and -not $ok) {
        $attempt++
        $suffix = if ($attempt -eq 1) { "" } else { "_retry" }
        $xml = Join-Path $reportDir ("chunk{0}{1}.xml" -f $chunkIndex, $suffix)
        $log = Join-Path $reportDir ("chunk{0}{1}.log" -f $chunkIndex, $suffix)
        $extra = ""
        if ($PytestArgs -ne "") { $extra = " " + $PytestArgs }
        # cmd /c 文件级重定向：绕开 PS5.1 将子进程 stderr 包装成 ErrorRecord、
        # 在 ErrorActionPreference=Stop 下变成终止错误的问题
        $cmdLine = "python -m pytest " + ($chunk -join ' ') + `
            " -q --no-header --junitxml=`"$xml`"$extra > `"$log`" 2>&1"
        cmd /c $cmdLine
        $code = $LASTEXITCODE
        # exit 0 = all green; 1 = test failures (real result, do not retry); 5 = no tests
        if ($code -eq 0 -or $code -eq 5) { $ok = $true }
        elseif ($code -eq 1 -and (Test-Path $xml)) {
            # A completed run with real failures: parse and accept as final.
            $ok = $true
        }
        else {
            Write-Host ("  chunk crashed (exit {0}), {1}" -f $code,
                $(if ($attempt -eq 1) { "retrying once" } else { "giving up after retry" }))
        }
    }

    if (Test-Path $xml) {
        $parsed = $false
        try {
            [xml]$junit = Get-Content $xml -Raw -Encoding UTF8
            $ts = $junit.testsuites.testsuite
            if ($ts -is [array]) { $ts = $ts[0] }
            $testsN = [int]$ts.tests
            $failuresN = [int]$ts.failures
            $errorsN = [int]$ts.errors
            $skippedN = [int]$ts.skipped
            $passedN = $testsN - $failuresN - $errorsN - $skippedN
            if ($ts.passed) { $passedN = [int]$ts.passed }
            $parsed = $true
        } catch {
            Write-Host ("  junitxml parse failed: {0}" -f $_.Exception.Message)
        }
        if ($parsed) {
            $grandPassed += $passedN
            $grandSkipped += $skippedN
            $grandFailed += $failuresN
            $grandErrors += $errorsN
            Write-Host ("  -> passed={0} skipped={1} failed={2} errors={3}" -f $passedN, $skippedN, $failuresN, $errorsN)
        } else {
            $grandErrors += $count
            Write-Host ("  -> counted {0} as errors (no parseable report)" -f $count)
        }
    }
    else {
        $grandErrors += $count
        Write-Host ("  -> chunk produced no report; counted {0} as errors" -f $count)
    }
}

Write-Host ("`n==== TOTAL: passed={0} skipped={1} failed={2} errors={3} ====" -f `
    $grandPassed, $grandSkipped, $grandFailed, $grandErrors)
Write-Host ("Reports: {0}" -f $reportDir)
if ($grandFailed -gt 0 -or $grandErrors -gt 0) { exit 1 }
exit 0
