call scripts\run_yaptide.bat %1

py .\yaptide_tester\yaptide_tester.py --do_monitor

call scripts\kill_yaptide.bat