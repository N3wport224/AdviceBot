@echo off
REM One-click Windows build for the Sabrina Zohar Advice Bot desktop app.
REM Produces dist\SabrinaAdvisor.exe. --windowed means NO console window ever
REM appears — the app opens straight into the chat UI.

pip install -r requirements-app.txt pyinstaller || goto :error

pyinstaller --noconfirm --onefile --windowed --name SabrinaAdvisor ^
  --icon assets\app.ico ^
  --hidden-import sklearn.feature_extraction.text ^
  --hidden-import sklearn.metrics.pairwise ^
  gui_app.py || goto :error

echo.
echo Build complete: dist\SabrinaAdvisor.exe
echo Optional: copy the data\ folder (built by run_pipeline.py) next to the
echo exe so answers are grounded in the scraped corpus.
pause
exit /b 0

:error
echo Build failed — see output above.
pause
exit /b 1
