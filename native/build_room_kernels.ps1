param([string]$LlvmBin = (Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin'))
$ErrorActionPreference = 'Stop'
& "$LlvmBin\clang.exe" --target=x86_64-pc-windows-msvc -mlong-double-80 -ffreestanding -fno-stack-protector -fno-builtin -ffp-contract=off -fno-fast-math -O2 -c "$PSScriptRoot\room_kernels.c" -o "$PSScriptRoot\room_kernels.obj"
if ($LASTEXITCODE) { throw 'Independent room kernel compilation failed' }
& "$LlvmBin\ld.lld.exe" -flavor link /machine:x64 /dll /noentry /nodefaultlib "/out:$PSScriptRoot\RoomKernels.dll" "$PSScriptRoot\room_kernels.obj"
if ($LASTEXITCODE) { throw 'Independent room kernel link failed' }
