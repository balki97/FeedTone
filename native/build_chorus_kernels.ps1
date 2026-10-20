param([string]$LlvmBin = (Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin'))
$ErrorActionPreference = 'Stop'
& "$LlvmBin\clang.exe" --target=x86_64-pc-windows-msvc -mlong-double-80 -ffreestanding -fno-stack-protector -fno-builtin -ffp-contract=off -fno-fast-math -O2 -c "$PSScriptRoot\chorus_kernels.c" -o "$PSScriptRoot\chorus_kernels.obj"
if ($LASTEXITCODE) { throw 'Independent chorus compilation failed' }
& "$LlvmBin\ld.lld.exe" -flavor link /machine:x64 /dll /noentry /nodefaultlib "/out:$PSScriptRoot\ChorusKernels.dll" "$PSScriptRoot\chorus_kernels.obj"
if ($LASTEXITCODE) { throw 'Independent chorus link failed' }
