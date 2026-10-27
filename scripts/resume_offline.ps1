# 18:00 解除手动离线，回到按作息自动判断（数据在 memory.db 的 runtime_state）
$ErrorActionPreference = "SilentlyContinue"
$Db = "D:\Code\Apps\AstrBot\data\plugin_data\astrbot_plugin_fatfish_memory\memory.db"
$Python = "D:\Code\Apps\AstrBot\.venv\Scripts\python.exe"
if (-not (Test-Path $Db)) { exit 0 }

$code = @'
import sqlite3, json
db = r"D:\Code\Apps\AstrBot\data\plugin_data\astrbot_plugin_fatfish_memory\memory.db"
c = sqlite3.connect(db)
row = c.execute("select value from runtime_state where namespace='offline' and key='control'").fetchone()
if row:
    d = json.loads(row[0])
    changed = False
    if d.get("manual") == "on":
        d["manual"] = "off"
        changed = True
    if d.get("silent"):
        d["silent"] = False
        changed = True
    if changed:
        c.execute("update runtime_state set value=? where namespace='offline' and key='control'",
                  (json.dumps(d, ensure_ascii=False),))
        c.commit()
        print("resumed")
c.close()
'@

$tmp = Join-Path $env:TEMP "fatfish_resume.py"
Set-Content -Path $tmp -Value $code -Encoding UTF8
& $Python $tmp
Add-Content -Path "D:\Code\Apps\AstrBot\watchdog.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') resume script ran"
Remove-Item $tmp -Force
