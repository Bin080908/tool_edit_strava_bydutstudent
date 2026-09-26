@echo off
title Strava FIT Studio - Banh Hoang Viet 26ES
color 0A
echo ================================================================
echo           STRAVA FIT STUDIO - BANH HOANG VIET 26ES
echo ================================================================
echo [*] Dang khoi dong may chu backend Python...
echo [*] Trinh duyet se tu dong mo: http://127.0.0.1:5000
echo.
echo LUU Y: Khong dong cua so nay trong luc su dung ung dung!
echo (Khi khong su dung nua, dong cua so nay de tat ung dung)
echo ================================================================
echo.

cd /d "%~dp0"
python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Co loi xay ra khi chay Python!
    pause
)
