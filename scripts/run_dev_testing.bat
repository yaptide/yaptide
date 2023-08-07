@REM 1 argument stands for yaptide being killed after tests or not
@REM 2 argument stands for yaptide tester mode
call scripts\run_yaptide.bat

@echo off
if "%2" == "jd" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_direct
) else if "%2" == "fd" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_direct
) else if "%2" == "jb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_batch
) else if "%2" == "fb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_batch
) else if "%2" == "jfd" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --test_files --run_direct
) else if "%2" == "jfb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --test_files --run_batch
) else if "%2" == "jdb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_jsons --run_direct --run_batch
) else if "%2" == "fdb" (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --test_files --run_direct --run_batch
) else (
    py .\yaptide_tester\yaptide_tester.py --do_monitor --all
)
@echo on

if "%1" == "no_kill" (
    echo "Leaving yaptide backend running"
) else (
    call scripts\kill_yaptide.bat
)