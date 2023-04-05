@REM 1 argument stands for shieldhit binary path
@REM 2 argument stands for plgrid username
@REM 3 argument stands for yaptide tester mode
call scripts\run_yaptide.bat %1 %2

@echo off
if "%3" == "1" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_direct
) else if "%3" == "2" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_direct
) else if "%3" == "3" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_batch
) else if "%3" == "4" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_batch
) else if "%3" == "5" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --test_files --run_direct
) else if "%3" == "6" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --test_files --run_batch
) else if "%3" == "7" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_direct --run_batch
) else if "%3" == "8" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_direct --run_batch
) else (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --all
)
@echo on

call scripts\kill_yaptide.bat