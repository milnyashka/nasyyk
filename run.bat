@echo off
chcp 65001 > nul
echo ========================================================
echo Запуск бота мониторинга Instagram и TikTok...
echo ========================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение .venv не найдено!
    echo Создаю .venv и устанавливаю зависимости...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
)

.venv\Scripts\python.exe bot.py
pause
