import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8006')}"
worker_class = "gthread"
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()

_json = {
    "()": "pythonjsonlogger.json.JsonFormatter",
    "fmt": "%(levelname)s %(name)s %(message)s",
    "rename_fields": {"levelname": "level", "name": "logger"},
    "timestamp": True,
}

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": _json},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["stdout"], "level": "INFO"},
    "loggers": {
        "gunicorn.error": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "gunicorn.access": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
    },
}
# gunicorn 26+ opens a control socket (for the gunicornc tool) in a default folder under $HOME.
# Our "app" user has no home folder, and the process is managed by Docker/Kubernetes signals,
# not gunicornc, so the socket is turned off.
control_socket_disable = True
