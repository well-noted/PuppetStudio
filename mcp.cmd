@echo off
rem Headless Puppet Studio MCP server on stdio. Usage: mcp.cmd --project "projects\my_project"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run setup.cmd first. 1>&2
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0studio.py" %* mcp
