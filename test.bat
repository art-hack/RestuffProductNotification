@echo off
:loop
    echo "Running the command..."
    python fetchStatus.py
    set /a num=%random% %%300 +300
    echo "Waiting %num% seconds"
    timeout /t %num%
    goto loop
