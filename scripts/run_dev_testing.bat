@REM 1 argument stands for shieldhit binary path
@REM 2 argument stands for plgrid username
@REM 3 argument stands for yaptide tester mode
@REM 4 argument stands for yaptide tester mode
call scripts\run_yaptide.bat %1

@echo off
if "%3" == "jd" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_direct
) else if "%3" == "fd" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_direct
) else if "%3" == "jb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_batch
) else if "%3" == "fb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_batch
) else if "%3" == "jfd" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --test_files --run_direct
) else if "%3" == "jfb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --test_files --run_batch
) else if "%3" == "jdb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_direct --run_batch
) else if "%3" == "fdb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_direct --run_batch
) else (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --all
)
@echo on

if "%2" == "no_kill" (
    echo "Leaving yaptide backend running"
) else (
    call scripts\kill_yaptide.bat
)