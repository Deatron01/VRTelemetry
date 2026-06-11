@echo off
echo =========================================
echo  VR TELEMETRY - AUTOMATIKUS BUILD SCRIPT
echo =========================================
echo.

echo [1/3] Frontend (React) leforditasa...
cd vr-telemetry-ui
call npm run build
cd ..
echo Frontend build KESZ!
echo.

echo [2/3] PyInstaller csomagolas...
:: Csak az openvr fuggoseget vonjuk be, az AI-t nem!
python -m PyInstaller --name "VR_Telemetry" --onedir --noconfirm --collect-all openvr --exclude-module torch --exclude-module whisper main.py
echo Csomagolas KESZ!
echo.

echo [3/3] Hordozhato mappa osszeallitasa...
:: 1. Atmasoljuk a Python scripteket (pl. run_pipeline.py) kozvetlenul az exe melle
copy "*.py" "dist\VR_Telemetry\" >nul

:: 2. Letrehozzuk a frontend mappajat az exe mellett, es belemadoljuk a buildet
mkdir "dist\VR_Telemetry\vr-telemetry-ui\dist" 2>nul
xcopy "vr-telemetry-ui\dist\*" "dist\VR_Telemetry\vr-telemetry-ui\dist\" /E /I /Y /Q
echo Fajlok a helyukre kerultek!

echo.
echo =========================================
echo MINDEN KESZ! 
echo.
echo A "dist\VR_Telemetry" mappa most mar 100%%-ig HORDOZHATO!
echo Zippelheted, felmasolhatod pendrive-ra, atviheted masik gepre, 
echo es a VR_Telemetry.exe mindent azonnal megtalal!
echo =========================================
pause