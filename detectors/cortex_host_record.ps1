param(
  [string]$WindowTitle = "Cortex IDE",
  [string]$ProcessName = "",
  [string]$OutputPath = "",
  [int]$DurationSec = 8,
  [int]$Fps = 20,
  [string]$FfmpegPath = "",
  [string]$ActionsJson = "",
  [switch]$ActionsOnly,
  [switch]$InstallFfmpeg
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:TargetProcessId = 0
$script:TargetWindowTitle = ""

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
  throw "OutputPath is required."
}

if ($DurationSec -lt 1) { $DurationSec = 1 }
if ($Fps -lt 5) { $Fps = 5 }

function Get-LocalFfmpegPath {
  $root = Join-Path $env:LOCALAPPDATA "Programs\ffmpeg"
  $exe = Join-Path $root "ffmpeg.exe"
  if (Test-Path $exe) { return $exe }
  return ""
}

function Install-LocalFfmpeg {
  $root = Join-Path $env:LOCALAPPDATA "Programs\ffmpeg"
  New-Item -ItemType Directory -Path $root -Force | Out-Null

  $zipPath = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
  $extractRoot = Join-Path $env:TEMP ("ffmpeg_extract_" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null

  $downloaded = $false
  $urls = @(
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
  )
  foreach ($u in $urls) {
    try {
      Invoke-WebRequest -UseBasicParsing -TimeoutSec 600 -Uri $u -OutFile $zipPath
      $downloaded = $true
      break
    } catch {
      continue
    }
  }
  if (-not $downloaded) {
    throw "Failed to download ffmpeg archive from all known sources."
  }
  Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force

  $ffmpegExe = Get-ChildItem -Path $extractRoot -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
  if ($null -eq $ffmpegExe) {
    throw "Failed to locate ffmpeg.exe in downloaded archive."
  }
  Copy-Item -Path $ffmpegExe.FullName -Destination (Join-Path $root "ffmpeg.exe") -Force

  $ffprobeExe = Get-ChildItem -Path $extractRoot -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
  if ($null -ne $ffprobeExe) {
    Copy-Item -Path $ffprobeExe.FullName -Destination (Join-Path $root "ffprobe.exe") -Force
  }

  Remove-Item -Path $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
  return (Join-Path $root "ffmpeg.exe")
}

function Resolve-FfmpegPath {
  param(
    [string]$Preferred,
    [bool]$AllowInstall
  )

  if (-not [string]::IsNullOrWhiteSpace($Preferred) -and (Test-Path $Preferred)) {
    return $Preferred
  }

  $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($null -ne $cmd -and (Test-Path $cmd.Source)) {
    return $cmd.Source
  }

  $local = Get-LocalFfmpegPath
  if (-not [string]::IsNullOrWhiteSpace($local)) {
    return $local
  }

  if ($AllowInstall) {
    return Install-LocalFfmpeg
  }

  throw "ffmpeg.exe not found. Re-run with -InstallFfmpeg to install a user-local copy."
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinApi {
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll", SetLastError=true)] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern int ShowCursor(bool bShow);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@
Add-Type -AssemblyName System.Windows.Forms

function Resolve-TargetWindow {
  param(
    [string]$TitleFragment,
    [string]$ExpectedProcessName = ""
  )

  $candidatesByTitle = Get-Process | Where-Object {
    $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -and $_.MainWindowTitle -like ("*" + $TitleFragment + "*")
  }
  $candidates = $candidatesByTitle
  if (-not [string]::IsNullOrWhiteSpace($ExpectedProcessName)) {
    $normalized = $ExpectedProcessName.Trim().ToLowerInvariant()
    $filtered = $candidatesByTitle | Where-Object {
      $_.ProcessName -and $_.ProcessName.ToLowerInvariant().Contains($normalized)
    }
    if ($filtered) {
      $candidates = $filtered
    }
  }
  if (-not $candidates) {
    # WSLg surfaces Linux app windows through mstsc.exe and title may be empty
    # for short intervals even when the window is visible.
    $candidates = Get-Process | Where-Object {
      $_.MainWindowHandle -ne 0 -and $_.ProcessName -eq "mstsc"
    }
  }
  $proc = $candidates | Sort-Object StartTime -Descending | Select-Object -First 1
  if ($null -eq $proc) {
    throw "No visible window found matching title fragment '$TitleFragment'."
  }

  [void][WinApi]::ShowWindowAsync($proc.MainWindowHandle, 9)
  [void][WinApi]::SetForegroundWindow($proc.MainWindowHandle)
  Start-Sleep -Milliseconds 300

  $rect = New-Object WinApi+RECT
  if (-not [WinApi]::GetWindowRect($proc.MainWindowHandle, [ref]$rect)) {
    throw "Failed to read window rectangle."
  }

  $width = [int]($rect.Right - $rect.Left)
  $height = [int]($rect.Bottom - $rect.Top)
  if ($proc.ProcessName -eq "mstsc" -and ($width -lt 800 -or $height -lt 500)) {
    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $rect.Left = [int]$bounds.Left
    $rect.Top = [int]$bounds.Top
    $rect.Right = [int]$bounds.Right
    $rect.Bottom = [int]$bounds.Bottom
    $width = [int]($rect.Right - $rect.Left)
    $height = [int]($rect.Bottom - $rect.Top)
  }
  if ($width -le 50 -or $height -le 50) {
    throw "Window rectangle is invalid: ${width}x${height}."
  }

  return [PSCustomObject]@{
    ProcessId = [int]$proc.Id
    ProcessName = $proc.ProcessName
    Title = if ([string]::IsNullOrWhiteSpace($proc.MainWindowTitle) -and $proc.ProcessName -eq "mstsc") { "Cortex IDE (Ubuntu)" } else { $proc.MainWindowTitle }
    Handle = $proc.MainWindowHandle
    Left = [int]$rect.Left
    Top = [int]$rect.Top
    Width = $width
    Height = $height
  }
}

function Invoke-MouseClick {
  param([string]$Button)
  switch ($Button.ToLowerInvariant()) {
    "right" {
      [WinApi]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero) # right down
      Start-Sleep -Milliseconds 40
      [WinApi]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero) # right up
    }
    default {
      [WinApi]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero) # left down
      Start-Sleep -Milliseconds 40
      [WinApi]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero) # left up
    }
  }
}

function Convert-HotkeyToSendKeys {
  param([string]$Hotkey)

  $raw = ""
  if ($null -ne $Hotkey) { $raw = [string]$Hotkey }
  $raw = $raw.Trim()
  if ([string]::IsNullOrWhiteSpace($raw)) { return "" }
  $parts = $raw.ToLowerInvariant().Split("+") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  if ($parts.Count -eq 0) { return "" }

  $mods = ""
  $keyToken = $parts[$parts.Count - 1]
  foreach ($p in $parts[0..([Math]::Max(0, $parts.Count - 2))]) {
    switch ($p) {
      "ctrl" { $mods += "^" }
      "control" { $mods += "^" }
      "alt" { $mods += "%" }
      "shift" { $mods += "+" }
      default { }
    }
  }

  switch ($keyToken) {
    "enter" { return $mods + "{ENTER}" }
    "return" { return $mods + "{ENTER}" }
    "esc" { return $mods + "{ESC}" }
    "escape" { return $mods + "{ESC}" }
    "tab" { return $mods + "{TAB}" }
    "space" { return $mods + " " }
    "up" { return $mods + "{UP}" }
    "down" { return $mods + "{DOWN}" }
    "left" { return $mods + "{LEFT}" }
    "right" { return $mods + "{RIGHT}" }
    "backspace" { return $mods + "{BACKSPACE}" }
    "delete" { return $mods + "{DELETE}" }
    "home" { return $mods + "{HOME}" }
    "end" { return $mods + "{END}" }
    "pageup" { return $mods + "{PGUP}" }
    "pagedown" { return $mods + "{PGDN}" }
    default {
      if ($keyToken -match "^f([1-9]|1[0-2])$") {
        return $mods + ("{" + $keyToken.ToUpperInvariant() + "}")
      }
      if ($keyToken.Length -eq 1) {
        return $mods + $keyToken
      }
      return $mods + ("{" + $keyToken.ToUpperInvariant() + "}")
    }
  }
}

function Send-KeySequence {
  param([string]$Keys)
  if ([string]::IsNullOrWhiteSpace($Keys)) { return }
  try {
    if ($script:TargetProcessId -gt 0) {
      [void][System.Windows.Forms.SendKeys]::Flush()
      $ws = New-Object -ComObject WScript.Shell
      $null = $ws.AppActivate([int]$script:TargetProcessId)
      Start-Sleep -Milliseconds 70
    } elseif (-not [string]::IsNullOrWhiteSpace($script:TargetWindowTitle)) {
      $ws = New-Object -ComObject WScript.Shell
      $null = $ws.AppActivate($script:TargetWindowTitle)
      Start-Sleep -Milliseconds 70
    }
    [System.Windows.Forms.SendKeys]::SendWait($Keys)
    Start-Sleep -Milliseconds 90
  } catch {
    # Best-effort input; continue recording even if SendKeys cannot target the window.
  }
}

function Send-TextLiteral {
  param([string]$Text)
  if ([string]::IsNullOrWhiteSpace($Text)) { return }
  $buffer = ""
  foreach ($ch in $Text.ToCharArray()) {
    switch ($ch) {
      '+' { $buffer += "{+}" }
      '^' { $buffer += "{^}" }
      '%' { $buffer += "{%}" }
      '~' { $buffer += "{~}" }
      '(' { $buffer += "{(}" }
      ')' { $buffer += "{)}" }
      '[' { $buffer += "{[}" }
      ']' { $buffer += "{]}" }
      '{' { $buffer += "{{}" }
      '}' { $buffer += "{}}" }
      default { $buffer += [string]$ch }
    }
  }
  if (-not [string]::IsNullOrWhiteSpace($buffer)) {
    Send-KeySequence $buffer
  }
}

function New-CursorOverlayIcon {
  param([string]$Path)
  Add-Type -AssemblyName System.Drawing
  $bmp = New-Object System.Drawing.Bitmap 26, 26, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.Clear([System.Drawing.Color]::Transparent)

  $points = [System.Drawing.Point[]]@(
    (New-Object System.Drawing.Point 2, 2),
    (New-Object System.Drawing.Point 2, 20),
    (New-Object System.Drawing.Point 8, 15),
    (New-Object System.Drawing.Point 11, 24),
    (New-Object System.Drawing.Point 14, 22),
    (New-Object System.Drawing.Point 10, 13),
    (New-Object System.Drawing.Point 19, 13)
  )
  $fill = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(245, 255, 255, 255))
  $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(255, 30, 30, 30)), 2.0

  $g.FillPolygon($fill, $points)
  $g.DrawPolygon($pen, $points)
  $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)

  $pen.Dispose()
  $fill.Dispose()
  $g.Dispose()
  $bmp.Dispose()
}

function Get-ActionField {
  param(
    [object]$Action,
    [string]$Name,
    $Default = $null
  )
  if ($null -eq $Action) { return $Default }
  if ($Action -is [System.Collections.IDictionary]) {
    if ($Action.Contains($Name)) { return $Action[$Name] }
    return $Default
  }
  $prop = $Action.PSObject.Properties[$Name]
  if ($null -eq $prop) { return $Default }
  return $prop.Value
}

function Get-Actions {
  param(
    [string]$RawJson,
    [int]$Duration
  )

  if (-not [string]::IsNullOrWhiteSpace($RawJson)) {
    return ($RawJson | ConvertFrom-Json)
  }

  # Default sequence for visible cursor movement while preserving app state.
  $d = [Math]::Max(4, $Duration)
  return @(
    @{ delayMs = 500;  xRatio = 0.20; yRatio = 0.06; click = $false; button = "left" },
    @{ delayMs = 700;  xRatio = 0.36; yRatio = 0.06; click = $false; button = "left" },
    @{ delayMs = 700;  xRatio = 0.56; yRatio = 0.06; click = $false; button = "left" },
    @{ delayMs = 700;  xRatio = 0.16; yRatio = 0.24; click = $false; button = "left" },
    @{ delayMs = 700;  xRatio = 0.16; yRatio = 0.32; click = $false; button = "left" },
    @{ delayMs = 700;  xRatio = 0.16; yRatio = 0.40; click = $false; button = "left" }
  )
}

function Ensure-ClickableActions {
  param(
    [object[]]$Actions
  )

  if ($null -ne $env:CORTEX_REQUIRE_ACTION_CLICK -and $env:CORTEX_REQUIRE_ACTION_CLICK -eq "0") {
    return @($Actions)
  }

  $arr = @($Actions)
  if ($arr.Count -eq 0) {
    return $arr
  }

  $hasClick = $false
  foreach ($a in $arr) {
    $clickRaw = Get-ActionField -Action $a -Name "click" -Default $null
    if ($null -ne $clickRaw -and [bool]$clickRaw) {
      $hasClick = $true
      break
    }
  }
  if ($hasClick) {
    return $arr
  }

  # Keep the action sequence but force one deterministic click interaction.
  $idx = [int][Math]::Floor($arr.Count / 2)
  $target = $arr[$idx]
  if ($target -is [System.Collections.IDictionary]) {
    $target["click"] = $true
    if (-not $target.Contains("button")) {
      $target["button"] = "left"
    }
  } else {
    if ($null -eq $target.PSObject.Properties["click"]) {
      Add-Member -InputObject $target -NotePropertyName "click" -NotePropertyValue $true -Force
    } else {
      $target.click = $true
    }
    if ($null -eq $target.PSObject.Properties["button"]) {
      Add-Member -InputObject $target -NotePropertyName "button" -NotePropertyValue "left" -Force
    } elseif ([string]::IsNullOrWhiteSpace([string]$target.button)) {
      $target.button = "left"
    }
  }

  return $arr
}

$ffmpeg = Resolve-FfmpegPath -Preferred $FfmpegPath -AllowInstall $InstallFfmpeg.IsPresent
$target = Resolve-TargetWindow -TitleFragment $WindowTitle -ExpectedProcessName $ProcessName
$script:TargetProcessId = [int]$target.ProcessId
$script:TargetWindowTitle = [string]$target.Title
$actions = Ensure-ClickableActions -Actions (Get-Actions -RawJson $ActionsJson -Duration $DurationSec)

$outputDir = Split-Path -Path $OutputPath -Parent
if (-not [string]::IsNullOrWhiteSpace($outputDir)) {
  New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

# Fast path for screenshot workflows that only need deterministic UI interactions.
if ($ActionsOnly.IsPresent) {
  for ($i = 0; $i -lt 8; $i++) {
    [void][WinApi]::ShowCursor($true)
  }

  foreach ($a in $actions) {
    $delay = 0
    $delayRaw = Get-ActionField -Action $a -Name "delayMs" -Default 0
    if ($null -ne $delayRaw) { $delay = [int]$delayRaw }
    if ($delay -gt 0) { Start-Sleep -Milliseconds $delay }

    $xRatio = 0.5
    $yRatio = 0.5
    $xRatioRaw = Get-ActionField -Action $a -Name "xRatio" -Default $null
    $yRatioRaw = Get-ActionField -Action $a -Name "yRatio" -Default $null
    if ($null -ne $xRatioRaw) { $xRatio = [double]$xRatioRaw }
    if ($null -ne $yRatioRaw) { $yRatio = [double]$yRatioRaw }

    $x = [int]([Math]::Round($target.Left + ($target.Width * $xRatio)))
    $y = [int]([Math]::Round($target.Top + ($target.Height * $yRatio)))
    if ($target.Handle -ne [IntPtr]::Zero) {
      [void][WinApi]::SetForegroundWindow($target.Handle)
    }
    [void][WinApi]::ShowCursor($true)
    [void][WinApi]::SetCursorPos($x, $y)

    $doClick = $false
    $clickRaw = Get-ActionField -Action $a -Name "click" -Default $null
    if ($null -ne $clickRaw) { $doClick = [bool]$clickRaw }
    if ($doClick) {
      $btn = "left"
      $btnRaw = Get-ActionField -Action $a -Name "button" -Default ""
      if (-not [string]::IsNullOrWhiteSpace([string]$btnRaw)) {
        $btn = [string]$btnRaw
      }
      Invoke-MouseClick -Button $btn
    }

    $hotkeyRaw = Get-ActionField -Action $a -Name "hotkey" -Default ""
    if (-not [string]::IsNullOrWhiteSpace([string]$hotkeyRaw)) {
      $keys = Convert-HotkeyToSendKeys -Hotkey ([string]$hotkeyRaw)
      Send-KeySequence $keys
    }
    $sendKeysRaw = Get-ActionField -Action $a -Name "sendKeys" -Default ""
    if (-not [string]::IsNullOrWhiteSpace([string]$sendKeysRaw)) {
      Send-KeySequence ([string]$sendKeysRaw)
    }
    $textRaw = Get-ActionField -Action $a -Name "text" -Default ""
    if (-not [string]::IsNullOrWhiteSpace([string]$textRaw)) {
      Send-TextLiteral ([string]$textRaw)
    }
    $pressEnter = $false
    $pressEnterRaw = Get-ActionField -Action $a -Name "pressEnter" -Default $null
    if ($null -ne $pressEnterRaw) { $pressEnter = [bool]$pressEnterRaw }
    if ($pressEnter) {
      Send-KeySequence "{ENTER}"
    }
  }

  Write-Output $OutputPath
  return
}

$ffArgs = @(
  "-y",
  "-f", "gdigrab",
  "-framerate", $Fps.ToString(),
  "-offset_x", $target.Left.ToString(),
  "-offset_y", $target.Top.ToString(),
  "-video_size", ("{0}x{1}" -f $target.Width, $target.Height),
  "-draw_mouse", "1",
  "-i", "desktop",
  "-t", $DurationSec.ToString(),
  "-vcodec", "libx264",
  "-preset", "ultrafast",
  "-crf", "23",
  "-pix_fmt", "yuv420p",
  "-movflags", "+faststart",
  $OutputPath
)

# Ensure cursor is visible to the capture backend.
for ($i = 0; $i -lt 8; $i++) {
  [void][WinApi]::ShowCursor($true)
}

$ff = Start-Process -FilePath $ffmpeg -ArgumentList $ffArgs -PassThru -WindowStyle Hidden
Start-Sleep -Milliseconds 250

foreach ($a in $actions) {
  if ($ff.HasExited) { break }
  $delay = 0
  $delayRaw = Get-ActionField -Action $a -Name "delayMs" -Default 0
  if ($null -ne $delayRaw) { $delay = [int]$delayRaw }
  if ($delay -gt 0) { Start-Sleep -Milliseconds $delay }
  if ($ff.HasExited) { break }

  $xRatio = 0.5
  $yRatio = 0.5
  $xRatioRaw = Get-ActionField -Action $a -Name "xRatio" -Default $null
  $yRatioRaw = Get-ActionField -Action $a -Name "yRatio" -Default $null
  if ($null -ne $xRatioRaw) { $xRatio = [double]$xRatioRaw }
  if ($null -ne $yRatioRaw) { $yRatio = [double]$yRatioRaw }

  $x = [int]([Math]::Round($target.Left + ($target.Width * $xRatio)))
  $y = [int]([Math]::Round($target.Top + ($target.Height * $yRatio)))
  if ($target.Handle -ne [IntPtr]::Zero) {
    [void][WinApi]::SetForegroundWindow($target.Handle)
  }
  [void][WinApi]::ShowCursor($true)
  [void][WinApi]::SetCursorPos($x, $y)

  $doClick = $false
  $clickRaw = Get-ActionField -Action $a -Name "click" -Default $null
  if ($null -ne $clickRaw) { $doClick = [bool]$clickRaw }
  if ($doClick) {
    $btn = "left"
    $btnRaw = Get-ActionField -Action $a -Name "button" -Default ""
    if (-not [string]::IsNullOrWhiteSpace([string]$btnRaw)) {
      $btn = [string]$btnRaw
    }
    Invoke-MouseClick -Button $btn
  }

  $hotkeyRaw = Get-ActionField -Action $a -Name "hotkey" -Default ""
  if (-not [string]::IsNullOrWhiteSpace([string]$hotkeyRaw)) {
    $keys = Convert-HotkeyToSendKeys -Hotkey ([string]$hotkeyRaw)
    Send-KeySequence $keys
  }
  $sendKeysRaw = Get-ActionField -Action $a -Name "sendKeys" -Default ""
  if (-not [string]::IsNullOrWhiteSpace([string]$sendKeysRaw)) {
    Send-KeySequence ([string]$sendKeysRaw)
  }
  $textRaw = Get-ActionField -Action $a -Name "text" -Default ""
  if (-not [string]::IsNullOrWhiteSpace([string]$textRaw)) {
    Send-TextLiteral ([string]$textRaw)
  }
  $pressEnter = $false
  $pressEnterRaw = Get-ActionField -Action $a -Name "pressEnter" -Default $null
  if ($null -ne $pressEnterRaw) { $pressEnter = [bool]$pressEnterRaw }
  if ($pressEnter) {
    Send-KeySequence "{ENTER}"
  }
}

$timeoutSec = [Math]::Max($DurationSec + 20, 30)
Wait-Process -Id $ff.Id -Timeout $timeoutSec -ErrorAction SilentlyContinue
if (-not $ff.HasExited) {
  Stop-Process -Id $ff.Id -Force
  throw "ffmpeg did not exit within timeout."
}
if ($ff.ExitCode -ne 0) {
  throw "ffmpeg failed with exit code $($ff.ExitCode)."
}
if (-not (Test-Path $OutputPath)) {
  throw "Recording output was not created: $OutputPath"
}

# Best-effort inline preview generation for issue bodies that cannot render MP4 tags.
try {
  $debugHostRecord = $false
  if ($null -ne $env:CORTEX_DEBUG_HOST_RECORD -and $env:CORTEX_DEBUG_HOST_RECORD -eq "1") {
    $debugHostRecord = $true
  }
  $outParent = Split-Path -Path $OutputPath -Parent
  $outStem = [System.IO.Path]::GetFileNameWithoutExtension($OutputPath)
  $inv = [System.Globalization.CultureInfo]::InvariantCulture
  $cursorEvents = @()
  $elapsedSec = 0.0
  foreach ($a in $actions) {
    $delay = 0
    $delayRaw = Get-ActionField -Action $a -Name "delayMs" -Default 0
    if ($null -ne $delayRaw) { $delay = [int]$delayRaw }
    $elapsedSec += ([double]$delay / 1000.0)

    $xRatio = 0.5
    $yRatio = 0.5
    $xRatioRaw = Get-ActionField -Action $a -Name "xRatio" -Default $null
    $yRatioRaw = Get-ActionField -Action $a -Name "yRatio" -Default $null
    if ($null -ne $xRatioRaw) { $xRatio = [double]$xRatioRaw }
    if ($null -ne $yRatioRaw) { $yRatio = [double]$yRatioRaw }

    $cx = [int]([Math]::Round($target.Width * $xRatio))
    $cy = [int]([Math]::Round($target.Height * $yRatio))
    $overlayX = [Math]::Max(0, $cx - 4)
    $overlayY = [Math]::Max(0, $cy - 4)
    $start = [Math]::Max(0.0, $elapsedSec - 0.10)
    $end = [Math]::Min([double]$DurationSec, $elapsedSec + 0.60)
    if ($end -le $start) { continue }
    $cursorEvents += [PSCustomObject]@{
      X = $overlayX
      Y = $overlayY
      Start = $start
      End = $end
    }
  }
  if ($debugHostRecord) {
    [Console]::Error.WriteLine("cursorEvents=" + $cursorEvents.Count)
    for ($i = 0; $i -lt $cursorEvents.Count; $i++) {
      $ev = $cursorEvents[$i]
      [Console]::Error.WriteLine(
        "event[$i]=x:" + [int]$ev.X + " y:" + [int]$ev.Y +
        " start:" + ([double]$ev.Start).ToString("0.000", $inv) +
        " end:" + ([double]$ev.End).ToString("0.000", $inv)
      )
    }
  }

  $cursorVideoPath = Join-Path $outParent ($outStem + ".cursor.mp4")
  if ($cursorEvents.Count -gt 0) {
    $cursorPng = Join-Path $env:TEMP ("cursor_overlay_" + [Guid]::NewGuid().ToString("N") + ".png")
    New-CursorOverlayIcon -Path $cursorPng

    $firstEvent = $cursorEvents[0]
    $xExpr = [int]$firstEvent.X
    $yExpr = [int]$firstEvent.Y
    for ($i = 1; $i -lt $cursorEvents.Count; $i++) {
      $event = $cursorEvents[$i]
      $xVal = [int]$event.X
      $yVal = [int]$event.Y
      $startVal = ([double]$event.Start).ToString("0.000", $inv)
      $xExpr = "if(lt(t\,${startVal})\,${xExpr}\,${xVal})"
      $yExpr = "if(lt(t\,${startVal})\,${yExpr}\,${yVal})"
    }
    $filterGraph = "[0:v][1:v]overlay=shortest=1:eof_action=pass:eval=frame:x=${xExpr}:y=${yExpr}[cv]"
    if ($debugHostRecord) {
      [Console]::Error.WriteLine("filterGraph=" + $filterGraph)
    }

    $cursorVideoPath = Join-Path $outParent ($outStem + ".cursor.mp4")
    $cursorVideoArgs = @(
      "-y",
      "-hide_banner",
      "-loglevel", "error",
      "-i", $OutputPath,
      "-loop", "1",
      "-i", $cursorPng,
      "-filter_complex", $filterGraph,
      "-map", "[cv]",
      "-an",
      "-vcodec", "libx264",
      "-preset", "ultrafast",
      "-crf", "23",
      "-pix_fmt", "yuv420p",
      "-movflags", "+faststart",
      $cursorVideoPath
    )
    & $ffmpeg @cursorVideoArgs | Out-Null
    if ($LASTEXITCODE -ne 0 -and (Test-Path $cursorVideoPath)) {
      Remove-Item -Path $cursorVideoPath -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $cursorPng) {
      Remove-Item -Path $cursorPng -Force -ErrorAction SilentlyContinue
    }
  }

  $gifPath = Join-Path $outParent ($outStem + ".preview.gif")
  # Default to cursor-overlay sidecar when available so pointer movement is always visible.
  # Set CORTEX_FORCE_RAW_GIF=1 to bypass overlay sidecar input.
  $gifInput = $OutputPath
  if (
    (Test-Path $cursorVideoPath) -and
    -not ($null -ne $env:CORTEX_FORCE_RAW_GIF -and $env:CORTEX_FORCE_RAW_GIF -eq "1")
  ) {
    $gifInput = $cursorVideoPath
  }

  # Use one-pass palette pipeline to preserve cursor shape in dark UI captures.
  $gifArgs = @(
    "-y",
    "-hide_banner",
    "-loglevel", "error",
    "-i", $gifInput,
    "-filter_complex", "fps=12,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=sierra2_4a",
    "-loop", "0",
    $gifPath
  )
  & $ffmpeg @gifArgs | Out-Null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $gifPath)) {
    if (Test-Path $gifPath) {
      Remove-Item -Path $gifPath -Force -ErrorAction SilentlyContinue
    }
    $fallbackGifArgs = @(
      "-y",
      "-hide_banner",
      "-loglevel", "error",
      "-i", $gifInput,
      # Keep native frame dimensions to avoid any apparent GUI blurring from scaling.
      "-vf", "fps=10",
      "-loop", "0",
      $gifPath
    )
    & $ffmpeg @fallbackGifArgs | Out-Null
    if ($LASTEXITCODE -ne 0 -and (Test-Path $gifPath)) {
      Remove-Item -Path $gifPath -Force -ErrorAction SilentlyContinue
    }
  }
} catch {
  # Ignore preview failures; main mp4 proof remains authoritative.
}

Write-Output $OutputPath
