param([string]$LlvmBin = (Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin'))
$ErrorActionPreference = 'Stop'
& "$LlvmBin\clang.exe" --target=x86_64-pc-windows-msvc -ffreestanding -fno-stack-protector -fno-builtin -ffp-contract=off -mlong-double-80 -O2 -c "$PSScriptRoot\cabinet_fft.c" -o "$PSScriptRoot\cabinet_fft.obj"
if ($LASTEXITCODE) { throw 'Cabinet FFT compilation failed' }
& "$LlvmBin\ld.lld.exe" -flavor link /machine:x64 /dll /noentry /nodefaultlib "/out:$PSScriptRoot\CabinetFFT.dll" "$PSScriptRoot\cabinet_fft.obj"
if ($LASTEXITCODE) { throw 'Cabinet FFT link failed' }
