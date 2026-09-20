# Run locally by the account owner; password is entered invisibly by Django.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8='1'
$env:DJANGO_DATABASE_PROFILE='temporary'
$env:POSTGRES_HOST='127.0.0.1'
$env:EDPEX_TEST_PORT='55469'
$env:EDPEX_TEST_DB_NAME='edpex_m1_public_ui'
$env:EDPEX_TEST_USER='postgres'
$env:EDPEX_TEST_PASSWORD=''
& .venv/Scripts/python.exe -B manage.py changepassword edpexadmin --settings=edpex.public_demo
