# DSH 插件安装：桌面版必须完全退出后再运行本脚本。
# 用法（管理员 PowerShell 可选）：
#   powershell -ExecutionPolicy Bypass -File scripts\dsh_install_plugins.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\dsh_install_plugins.ps1 -Profile desktop -DryRun

param(
    [string]$Profile = "desktop",
    [switch]$DryRun,
    [switch]$IncludeQqBridge,
    [switch]$IncludeCommunity,
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
    @{ Name = "dsh-obsidian";       Why = "私人笔记只读查询（MIT）";           Required = $true }
)
# 插件工坊1.6.2写死web profile，暂不装进Desktop。
# B站文本/插件发现使用prepare_dsh_community.py的固定来源适配归档。
if ($IncludeCommunity) {
    if ($DryRun) {
        Say 'would prepare reviewed community archives: dsh-plugin-bilibili 0.2.4 / dsh-find-plugin 0.4.0'
    } else {
        & (Join-Path $Repo '.tools/dsh-python/Scripts/python.exe') (Join-Path $Repo 'scripts/prepare_dsh_community.py')
        if ($LASTEXITCODE -ne 0) { throw '社区归档准备失败' }
        $community = Get-Content (Join-Path $Repo '.tools/dsh-vendor/adapted/community-current.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($item in $community) {
            $actual = (Get-FileHash -LiteralPath $item.archive -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $item.sha256) { throw '社区归档SHA256不一致' }
            $plugins += @{ Name = "file:$($item.archive.Replace('\', '/'))"; Why = '固定版本社区适配包（MIT）'; Required = $true }
        }
    }
}
if ($IncludeQqBridge -and -not $SkipQqBridge) {
    $manifest = Get-Content (Join-Path $ProfileDir 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.dsh.profile.bundles -notcontains 'dsh-fatfish-life') {
        throw 'QQ适配需要FatFish管理服务；先完全退出DSH并运行 scripts/dsh_install_control.py'
    }
    $archive = "<prepare_dsh_onebot.py --pack生成的归档>"
    if (-not $DryRun) {
        & (Join-Path $Repo ".tools\dsh-python\Scripts\python.exe") -X utf8 (Join-Path $Repo "scripts\prepare_dsh_onebot.py") --pack
        if ($LASTEXITCODE -ne 0) { throw "QQ桥准备失败，停止安装" }
        $archive = (Get-Content (Join-Path $Repo '.tools\dsh-vendor\adapted\onebot-current.json') -Raw -Encoding UTF8 | ConvertFrom-Json).archive
    }
    $plugins += @{ Name = "file:$($archive.Replace('\', '/'))"; Why = "QQ 接入（BSD-3，本地适配归档；仅P5明确启用）"; Required = $true }
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
    & $Cli plugin --profile $Profile add $p.Name --ignore-scripts
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
