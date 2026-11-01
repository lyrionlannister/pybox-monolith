"""Logger de la app: rota archivos diariamente y los organiza en carpetas mensuales."""

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from core.tools.config_tools import get_or_throw


class MonthlyDailyRotatingFileHandler(TimedRotatingFileHandler):
    """Extiende TimedRotatingFileHandler para agrupar los logs en carpetas por mes."""

    def __init__(
        self,
        base_dir="./logs",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding=None,
    ):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self.current_month = None
        log_path = self._get_log_path()
        super().__init__(
            log_path,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
        )

    def _get_log_path(self):
        now = datetime.now()
        month_folder = os.path.join(self.base_dir, now.strftime("%Y-%m"))
        os.makedirs(month_folder, exist_ok=True)
        return os.path.join(month_folder, now.strftime("%Y-%m-%d") + ".log")

    def doRollover(self):
        """Recalcula la ruta (puede caer en un mes nuevo) antes de rotar el archivo."""
        self.stream.close()
        self.baseFilename = self._get_log_path()
        self.stream = self._open()


class Logger:
    """Singleton del logger: consola en desarrollo, archivo con rotación en el resto."""

    _ENVIROMENT = get_or_throw("ENV")

    @classmethod
    def get_logger(cls):
        if not hasattr(cls, "_logger_instance"):
            cls._logger_instance = cls()
        return cls._logger_instance.logger

    def __init__(self):
        self.logger = logging.getLogger("TEMPLATE")

        if not self.logger.hasHandlers():
            self.formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
            )

            if self._ENVIROMENT == "development":
                handler = logging.StreamHandler()
                handler.setLevel(logging.DEBUG)
                handler.setFormatter(self.formatter)
                self.logger.setLevel(logging.DEBUG)
            else:
                handler = MonthlyDailyRotatingFileHandler("./logs")
                handler.setLevel(logging.INFO)
                handler.setFormatter(self.formatter)
                self.logger.setLevel(logging.INFO)

            self.logger.propagate = False
            self.logger.addHandler(handler)


logger = Logger.get_logger()


def silence_pool_shutdown_noise() -> None:
    """Sube el nivel del logger del pool de SQLAlchemy para el apagado.

    Al recibir la señal de parada, las conexiones que quedaron tomadas por un job
    cancelado se terminan de forma abrupta y SQLAlchemy vuelca 'Exception terminating
    connection' (ruido inofensivo del cierre). Se llama justo antes de disponer el
    engine para que ese cierre no ensucie los logs de apagado.
    """
    logging.getLogger("sqlalchemy.pool").setLevel(logging.CRITICAL)
