@echo off
if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe manage.py runserver %*
) else if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe manage.py runserver %*
) else (
    python manage.py runserver %*
)
