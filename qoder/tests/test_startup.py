"""Execute the real startup scripts with controlled process/health commands.

These lifecycle regressions do not replace real PowerContext integration tests.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = ["timeout", "early_exit", "ready", "reused", "app_failure"]


@pytest.mark.parametrize("case", CASES)
def test_powershell_startup(case):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell or os.name != "nt":
        pytest.skip("Windows PowerShell lifecycle test")
    # Mock only external commands. Run the unchanged script, including its
    # real wait deadline, exception propagation and finally cleanup.
    command = r'''
$env:PC_START_TIMEOUT = '1'
$global:calls = 0
$global:started = $false
$global:app = $false
$global:cleaned = $false
$global:failed = $false
$case = $env:STARTUP_TEST_CASE
function Invoke-WebRequest {
    $global:calls++
    if ($case -eq 'reused' -or (($case -eq 'ready' -or $case -eq 'app_failure') -and $global:calls -gt 1)) {
        return [pscustomobject]@{StatusCode=200}
    }
    throw 'Controlled unavailable service'
}
function Start-Process {
    $global:started = $true
    $process = [pscustomobject]@{Id=424242;HasExited=($case -eq 'early_exit');ExitCode=7}
    $process | Add-Member -MemberType ScriptMethod -Name Refresh -Value {}
    return $process
}
function taskkill.exe { $global:cleaned = $true }
function python {
    $global:app = $true
    $global:LASTEXITCODE = if ($case -eq 'app_failure') { 9 } else { 0 }
}
try { & $env:STARTUP_TEST_SCRIPT } catch { $global:failed = $true; $global:errorMessage = $_.Exception.Message }
@{started=$global:started;app=$global:app;cleaned=$global:cleaned;failed=$global:failed;error=$global:errorMessage} | ConvertTo-Json -Compress
'''
    env = dict(os.environ, STARTUP_TEST_CASE=case, STARTUP_TEST_SCRIPT=str(ROOT / "start.ps1"))
    result = subprocess.run([shell, "-NoProfile", "-Command", command], env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["app"] == (case in ("ready", "reused", "app_failure")), receipt
    assert receipt["failed"] == (case in ("timeout", "early_exit", "app_failure"))
    assert receipt["started"] == (case != "reused"), receipt
    assert receipt["cleaned"] == (case in ("timeout", "ready", "app_failure"))


@pytest.mark.parametrize("case", CASES)
def test_bash_startup(case, tmp_path):
    shell = os.environ.get("STUDYRELAY_TEST_BASH")
    if not shell and os.name != "nt":
        shell = shutil.which("bash")
    if not shell:
        pytest.skip("Bash unavailable; set STUDYRELAY_TEST_BASH to enable on Windows")
    # Exported shell functions substitute only curl/server/app commands.
    command = r'''
curl() {
    if [ "$STARTUP_TEST_CASE" = reused ] || [ -f "$STARTUP_TEST_DIR/ready" ]; then return 0; fi
    return 1
}
powercontext() {
    echo "$BASHPID" > "$STARTUP_TEST_DIR/pid"
    if [ "$STARTUP_TEST_CASE" = early_exit ]; then return 7; fi
    trap 'echo cleaned > "$STARTUP_TEST_DIR/cleaned"; exit 0' TERM
    if [ "$STARTUP_TEST_CASE" = ready ] || [ "$STARTUP_TEST_CASE" = app_failure ]; then
        touch "$STARTUP_TEST_DIR/ready"
    fi
    while true; do sleep 0.1; done
}
python() {
    echo APP_STARTED
    if [ "$STARTUP_TEST_CASE" = app_failure ]; then return 9; fi
}
export -f curl powercontext python
bash "$STARTUP_TEST_SCRIPT"
'''
    env = dict(os.environ, PC_START_TIMEOUT="3", STARTUP_TEST_CASE=case,
               STARTUP_TEST_SCRIPT=(ROOT / "start.sh").as_posix(), STARTUP_TEST_DIR=tmp_path.as_posix())
    result = subprocess.run([shell, "-c", command], env=env, capture_output=True,
                            text=True, timeout=20)
    assert ("APP_STARTED" in result.stdout) == (case in ("ready", "reused", "app_failure"))
    assert (result.returncode != 0) == (case in ("timeout", "early_exit", "app_failure"))
    assert (tmp_path / "pid").exists() == (case != "reused")
    assert (tmp_path / "cleaned").exists() == (case in ("timeout", "ready", "app_failure"))
