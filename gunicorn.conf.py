# Gunicorn settings — auto-loaded from ./gunicorn.conf.py even when the
# server is started as a bare `gunicorn app:app` (which is what Render's
# auto-detected start command does). This is why the timeout flags from the
# Procfile / render.yaml were being ignored.
#
# Setting threads > 1 makes gunicorn use the threaded (gthread) worker, so a
# long PDF parse on one thread doesn't block health checks on another.

timeout = 120     # allow the slow free-tier CPU to finish parsing big bills
workers = 1       # one worker keeps memory low on the 512 MB free instance
threads = 4       # serve health checks / concurrent requests during parsing
