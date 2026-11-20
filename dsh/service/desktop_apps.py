"""Read the status of explicitly supported local Windows applications."""

import json
import os
import subprocess
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Literal


DesktopApp = Literal['outlook', 'automas', 'xuexitong', 'all']
_APPS = ('outlook', 'automas', 'xuexitong')
_AUTOMAS_PORT = 36163
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_WINDOWS_OPEN = r"""
$ErrorActionPreference = 'Stop'
$patterns = @{
    outlook = '^(Microsoft\.OutlookForWindows_[A-Za-z0-9_]+!Microsoft\.OutlookforWindows|Microsoft\.Office\.OUTLOOK\.EXE\.[A-Za-z0-9.]+)$'
    'outlook-classic' = '^Microsoft\.Office\.OUTLOOK\.EXE\.[A-Za-z0-9.]+$'
    automas = '^[A-Za-z]:[\\/][^\r\n]+[\\/]AUTO-MAS\.exe$'
    xuexitong = '^[A-Za-z]:[\\/][^\r\n]+[\\/]cxstudy\.exe$'
}
$key = $env:FATFISH_WECHAT_OPEN_APP
if (!$patterns.ContainsKey($key)) { exit 2 }
$entry = Get-StartApps | Where-Object { $_.AppID -match $patterns[$key] } | Select-Object -First 1
if (!$entry) { exit 3 }
if ($key -in 'outlook','outlook-classic') {
    Start-Process -FilePath "$env:SystemRoot\explorer.exe" -ArgumentList ('shell:AppsFolder\' + $entry.AppID)
} elseif ([System.IO.File]::Exists($entry.AppID)) {
    Start-Process -FilePath $entry.AppID -WorkingDirectory ([System.IO.Path]::GetDirectoryName($entry.AppID))
} else { exit 3 }
"""


def open_desktop_app(app: str) -> dict:
    if app not in (*_APPS, "outlook-classic"):
        return {"ok": False, "reason": "unsupported-app"}
    if os.name != "nt":
        return {"ok": False, "reason": "windows-only"}
    try:
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_OPEN],
                                env={**os.environ, "FATFISH_WECHAT_OPEN_APP": app},
                                capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError, KeyError):
        return {"ok": False, "reason": "launch-unavailable"}
    if result.returncode:
        return {"ok": False, "reason": "app-entry-not-found" if result.returncode == 3 else "launch-unavailable"}
    return {"ok": True, "status": "launch-requested", "app": app}

_WINDOWS_MAIL = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try { $outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') } catch { exit 3 }
$items = $outlook.GetNamespace('MAPI').GetDefaultFolder(6).Items
$items.Sort('[ReceivedTime]', $true)
$china = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$today = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $china).Date
$rows = @()
for ($i = 1; $i -le [Math]::Min($items.Count, 30); $i++) {
    $item = $items.Item($i)
    if ($item.Class -ne 43) { continue }
    $received = [TimeZoneInfo]::ConvertTimeFromUtc(([DateTime]$item.ReceivedTime).ToUniversalTime(), $china)
    if ($received.Date -lt $today) { break }
    if ($received.Date -ne $today) { continue }
    $subject = [string]$item.Subject
    $body = [string]$item.Body
    $rows += @{ subject = $subject.Substring(0, [Math]::Min(100, $subject.Length))
        received = $received.ToString('HH:mm')
        preview = $body.Substring(0, [Math]::Min(220, $body.Length)) }
    if ($rows.Count -ge 10) { break }
}
@{ messages = $rows; limited = ($rows.Count -ge 10) } | ConvertTo-Json -Compress
"""


def outlook_today() -> dict:
    """Read only the default inbox of an already signed-in classic Outlook instance."""
    if os.name != "nt":
        return {"ok": False, "reason": "windows-only"}
    try:
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-STA", "-Command", _WINDOWS_MAIL],
                                capture_output=True, text=True, encoding="utf-8", timeout=8,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            return {"ok": False, "reason": "classic-outlook-not-running" if result.returncode == 3 else "mail-unavailable"}
        data = json.loads(result.stdout)
        rows = data.get("messages")
        if not isinstance(rows, list):
            return {"ok": False, "reason": "mail-unavailable"}
        return {"ok": True, "messages": rows[:10], "limited": data.get("limited") is True}
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, UnicodeError, AttributeError):
        return {"ok": False, "reason": "mail-unavailable"}


_WINDOWS_STATUS = r'''
$ErrorActionPreference = 'Stop'
$entries = @(Get-StartApps)
$processes = @(Get-Process -Name 'OUTLOOK', 'olk', 'AUTO-MAS', 'cxstudy' -ErrorAction SilentlyContinue)
@{
    outlook = @{
        shortcut_found = [bool]($entries.AppID -match '^(Microsoft\.OutlookForWindows_|Microsoft\.Office\.OUTLOOK\.EXE\.)')
        process_running = [bool]($processes.ProcessName -match '^(OUTLOOK|olk)$')
    }
    automas = @{
        shortcut_found = [bool]($entries.AppID -match '(^|[\\/])AUTO-MAS\.exe$')
        process_running = [bool]($processes.ProcessName -match '^AUTO-MAS$')
    }
    xuexitong = @{
        shortcut_found = [bool]($entries.AppID -match '(^|[\\/])cxstudy\.exe$')
        process_running = [bool]($processes.ProcessName -match '^cxstudy$')
    }
} | ConvertTo-Json -Compress
'''


def _windows_status() -> dict:
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-NonInteractive', '-Command', _WINDOWS_STATUS],
        capture_output=True, encoding='utf-8', timeout=8, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return json.loads(result.stdout)


def _get_automas(path: str) -> dict:
    # Direct loopback GETs avoid proxy settings and never follow redirects.
    connection = HTTPConnection('127.0.0.1', _AUTOMAS_PORT, timeout=2)
    try:
        connection.request('GET', path)
        with connection.getresponse() as response:
            if response.status != 200:
                raise ValueError('unexpected response status')
            data = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(data) > _MAX_RESPONSE_BYTES:
                raise ValueError('response too large')
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError('unexpected response shape')
            return payload
    finally:
        connection.close()


def _automas_status() -> dict:
    try:
        health = _get_automas('/api/core/health')
    except (OSError, HTTPException):
        return {'backend': 'unreachable'}
    except (ValueError, UnicodeError):
        return {'backend': 'unverified'}
    state = health.get('backgroundStatus')
    if (health.get('ready') is not True or type(health.get('protocol')) is not int
            or state not in ('starting', 'running', 'ready', 'failed', 'cancelled')):
        return {'backend': 'unverified'}
    if state != 'ready':
        return {'backend': state}
    try:
        snapshot = _get_automas('/api/dispatch/runtime-snapshot')
        tasks, scheduled = snapshot.get('tasks'), snapshot.get('scheduledScripts')
        if (not isinstance(tasks, list) or not isinstance(scheduled, list)
                or any(not isinstance(task, dict) for task in tasks)):
            raise ValueError('unexpected task snapshot shape')
        return {
            'backend': 'ready',
            'active_tasks': len(tasks),
            'stopping_tasks': sum(task.get('stopping') is True for task in tasks),
            'scheduled_scripts': len(scheduled),
        }
    except (OSError, HTTPException, ValueError, UnicodeError):
        return {'backend': 'ready', 'task_snapshot': 'unavailable'}


def desktop_status(app: DesktopApp) -> dict:
    if app not in (*_APPS, 'all'):
        return {'ok': False, 'reason': 'unsupported-app'}
    if os.name != 'nt':
        return {'ok': False, 'reason': 'windows-only'}
    try:
        windows = _windows_status()
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, UnicodeError):
        return {'ok': False, 'reason': 'windows-status-unavailable'}
    selected = _APPS if app == 'all' else (app,)
    states = {name: windows[name] for name in selected}
    if 'automas' in states:
        states['automas'].update(_automas_status())
    return {'ok': True, 'apps': states}
