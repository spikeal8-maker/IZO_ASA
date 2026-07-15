@echo off
"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Sleep -Seconds 30; & 'C:\izo-generator\tools\start-production-stack.ps1'"
