param([string]$LlvmBin = (Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin'))
$ErrorActionPreference = 'Stop'
& "$LlvmBin\clang.exe" --target=x86_64-pc-windows-msvc -mlong-double-80 -ffreestanding -fno-stack-protector -fno-builtin -ffp-contract=off -fno-fast-math -O2 -c "$PSScriptRoot\reverb_kernels.c" -o "$PSScriptRoot\reverb_kernels.obj"
if ($LASTEXITCODE) { throw 'Independent reverb kernel compilation failed' }
& "$LlvmBin\ld.lld.exe" -flavor link /machine:x64 /dll /noentry /nodefaultlib "/out:$PSScriptRoot\ReverbKernels.dll" "$PSScriptRoot\reverb_kernels.obj"
if ($LASTEXITCODE) { throw 'Independent reverb kernel link failed' }
