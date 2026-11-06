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