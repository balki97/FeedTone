param([string]$LlvmBin = (Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin'))
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
& "$LlvmBin\llvm-dlltool.exe" -m i386:x86-64 -d "$sourceRoot\kernel32.def" -l "$sourceRoot\kernel32.lib"
if ($LASTEXITCODE) { throw 'Import library generation failed' }
& "$LlvmBin\clang.exe" --target=x86_64-pc-windows-msvc -ffreestanding -fno-stack-protector -fno-builtin -O1 -c "$sourceRoot\bridge.c" -o "$sourceRoot\bridge.obj"
if ($LASTEXITCODE) { throw 'VST transport compilation failed' }
& "$LlvmBin\ld.lld.exe" -flavor link /machine:x64 /dll /entry:DllMain /subsystem:windows /nodefaultlib "/out:$sourceRoot\..\FeedTone.vst3" "$sourceRoot\bridge.obj" "$sourceRoot\kernel32.lib"
if ($LASTEXITCODE) { throw 'VST transport link failed' }
