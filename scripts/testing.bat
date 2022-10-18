@REM set mypath=%~dp0
@REM echo %mypath:~0,-1%

@REM set mypath=%~dp0..\
@REM echo %mypath:~0,-1%

@ECHO OFF
ECHO %~dp0
ECHO %~dp0..\
FOR %%A IN ("%~dp0.") DO ECHO %%~dpA
FOR %%A IN ("%~dp0.") DO SET folder=%%~dpA
echo %folder%