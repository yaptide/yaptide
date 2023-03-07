@REM 1 argument stands for shieldhit binary path
@REM 2 argument stands for plgrid username
call scripts\run_yaptide.bat %1 %2

py .\yaptide_tester\yaptide_tester.py --do_monitor

call scripts\kill_yaptide.bat