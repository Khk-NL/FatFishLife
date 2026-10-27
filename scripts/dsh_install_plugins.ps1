# DSH 插件安装：桌面版必须完全退出后再运行本脚本。
# 用法（管理员 PowerShell 可选）：
#   powershell -ExecutionPolicy Bypass -File scripts\dsh_install_plugins.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\dsh_install_plugins.ps1 -Profile desktop -DryRun

param(
    [string]$Profile = "desktop",
    [switch]$DryRun,
    [switch]$SkipQqBridge
)

$ErrorActionPreference = "Stop"
$DshHome = Join-Path $env:USERPROFILE ".dsh"
$ProfileDir = Join-Path $DshHome "profiles\$Profile"
$Cli = "D:\dsh\resources\runtime\cli\bin\dsh.cmd"
$Repo = "D:\Code\Projects\FatFishLife"

function Say($msg) { Write-Host "[dsh-install] $msg" }

# 1. 运行中不能装
$running = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue
if ($running) {
    Say "检测到 DeepSeek Harness 正在运行（$($running.Count) 个进程）。请完全退出（含托盘）后重试。"
    exit 1
}

if (-not (Test-Path $Cli)) { Say "找不到 CLI：$Cli"; exit 1 }
if (-not (Test-Path $ProfileDir)) { Say "找不到 profile：$ProfileDir"; exit 1 }

# 2. 插件清单：名称、用途、是否必装
$plugins = @(
    @{ Name = "dsh-knowledge-base"; Why = "公开设定资料 KB（MIT，FTS5/BM25）"; Required = $true },
    @{ Name = "dsh-obsidian";       Why = "私人笔记只读查询（MIT）";           Required = $true },
    @{ Name = "dsh-plugin-workshop"; Why = "应用内插件浏览器，之后自助装插件"; Required = $false }
)
if (-not $SkipQqBridge) {
    $plugins += @{ Name = "dsh-onebot-qq"; Why = "QQ 接入（BSD-3，配套 FatFish 策略补丁）"; Required = $true }
}

Say "profile: $Profile"
Say "目标目录: $ProfileDir"
Say ""

foreach ($p in $plugins) {
    if ($DryRun) {
        Say "would run: dsh plugin --profile $Profile add $($p.Name)   # $($p.Why)"
        continue
    }
    Say "安装 $($p.Name) ..."
    & $Cli plugin --profile $Profile add $p.Name
    if ($LASTEXITCODE -ne 0) {
        if ($p.Required) { Say "必装插件 $($p.Name) 失败，停止"; exit 1 }
        Say "可选插件 $($p.Name) 失败，跳过"
    }
}

# 3. 写入 FatFish 自己的 patch 层（MCP 记忆 + 人格 preset）
if (-not $DryRun) {
    $patchFile = Join-Path $ProfileDir "cordis.patch.yml"
    if (-not (Test-Path $patchFile)) { Set-Content -Path $patchFile -Value "# dsh patch layer`n[]" -Encoding UTF8 }

    $marker = "# >>> fatfish-managed"
    $existing = Get-Content -Path $patchFile -Raw -Encoding UTF8
    if ($existing -notlike "*$marker*") {
        $mcp = Get-Content -Path (Join-Path $Repo "dsh\mcp-fatfish.yml") -Raw -Encoding UTF8
        $preset = Get-Content -Path (Join-Path $Repo "dsh\preset-apple-le.yml") -Raw -Encoding UTF8
        $block = "`n$marker`n$mcp`n$preset`n# <<< fatfish-managed`n"
        Add-Content -Path $patchFile -Value $block -Encoding UTF8
        Say "已把 MCP 记忆与 apple-social preset 写入 cordis.patch.yml"
    } else {
        Say "cordis.patch.yml 已有 fatfish-managed 段，跳过（如需更新请先删除该段）"
    }
}

Say ""
Say "完成。启动 DeepSeek Harness 后，设置 → 插件 里应能看到已装插件。"
Say "QQ 桥需要单独配置：profile 的 cordis.patch.yml 里 dsh-onebot 行填 NapCat 的 WS 地址与 botQQ。"
