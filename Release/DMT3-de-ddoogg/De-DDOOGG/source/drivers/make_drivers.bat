@echo off
rem ============================================================
rem  Build itoken2.sys + vrockey6.sys (x64 kernel drivers)
rem  Prerequisites:
rem    - Visual Studio BuildTools (MSVC x64 toolchain)
rem    - Windows SDK/WDK 10 (tested with 10.0.28000.0)
rem  Adjust the three paths below to your machine, then run.
rem  Output: itoken2.sys / vrockey6.sys in this directory.
rem  Sign afterwards with your own test certificate, e.g.:
rem    makecat itoken2.cdf   & signtool sign /fd sha256 /s My /n "YourTestCert" itoken2.sys itoken2.cat
rem    makecat vrockey6.cdf  & signtool sign /fd sha256 /s My /n "YourTestCert" vrockey6.sys vrockey6.cat
rem ============================================================
setlocal
set WDK=C:\Program Files (x86)\Windows Kits\10
set VER=10.0.28000.0
set VS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools
set MSVC=%VS%\VC\Tools\MSVC\14.51.36231

call "%VS%\VC\Auxiliary\Build\vcvarsall.bat" x64 >nul 2>&1

set INC=/I"%WDK%\Include\%VER%\km" /I"%WDK%\Include\%VER%\shared" /I"%WDK%\Include\%VER%\um" /I"%MSVC%\include" /I"%WDK%\Include\%VER%\ucrt"
set DEF=/DUNICODE /D_UNICODE /DNTDDI_VERSION=0x0A00000C /D_WIN32_WINNT=0x0A00 /DWIN32_LEAN_AND_MEAN /D_AMD64_
set LIBS="%WDK%\Lib\%VER%\km\x64\ntoskrnl.lib" "%WDK%\Lib\%VER%\km\x64\BufferOverflowFastFailK.lib" /LIBPATH:"%WDK%\Lib\%VER%\km\x64" /LIBPATH:"%MSVC%\lib\x64"

cl /nologo /c /O1 /GS- /Gz /Fo:itoken2.obj itoken2.c %INC% %DEF% || goto :err
link /nologo /DRIVER /ENTRY:DriverEntry /SUBSYSTEM:NATIVE /OUT:itoken2.sys itoken2.obj %LIBS% || goto :err

cl /nologo /c /O1 /GS- /Gz /W3 /Fo:vrockey6.obj vrockey6.c %INC% %DEF% || goto :err
link /nologo /DRIVER /ENTRY:DriverEntry /SUBSYSTEM:NATIVE /OUT:vrockey6.sys vrockey6.obj %LIBS% || goto :err

echo.
echo Build OK: itoken2.sys vrockey6.sys
exit /b 0

:err
echo Build FAILED
exit /b 1
