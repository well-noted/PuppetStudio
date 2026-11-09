"""Headless, agent-facing control layer for Puppet Studio.

The modules here wrap the same project actions the browser Studio uses
(``studio.core.action``) and add what an autonomous agent needs to work
without a browser: images it can look at, speaker analysis, reference-frame
ranking, artwork checks and background jobs. ``mcp_server`` exposes the tool
registry in ``tools`` over the Model Context Protocol (stdio); ``studio.py
agent`` exposes the same tools on the command line.
"""
