@echo off
venv\Scripts\python -m tests.test_ingestion > test_output.txt 2>&1
type test_output.txt
