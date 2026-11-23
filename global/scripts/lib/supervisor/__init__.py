"""supervisor-lock: one session supervisor per project. One module per responsibility.

Modules import each other as modules and resolve names at call time (`census.collect_sessions()`), so that
call-time cycles work and a patch of the owner reaches every caller.
"""
