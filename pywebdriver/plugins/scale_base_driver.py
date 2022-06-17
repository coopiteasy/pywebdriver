# SPDX-FileCopyrightText: 2022 Coop IT Easy SCRLfs
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Class API for implementing a weighing scale."""

import logging
import time
from abc import ABC, abstractmethod
from contextlib import ExitStack
from threading import Lock, Thread

from .base_driver import AbstractDriver

_logger = logging.getLogger(__name__)


class ScaleDriver(AbstractDriver, ABC):
    def __init__(self, scale_connection_thread):
        super().__init__()

        self.scale_connection_thread = scale_connection_thread

    def create_flask_routes(self):
        # TODO
        pass


class ScaleConnectionThread(Thread, ABC):
    def __init__(self, config, *args, **kwargs):
        super().__init__(*args, daemon=True, **kwargs)
        self.config = config
        self.data = {}
        self.lock = Lock()

    @property
    @abstractmethod
    def weight(self):
        """Return the last reported weight of the scale."""
        # Read this from self.data. Use self.lock.

    @abstractmethod
    def acquire_data(self, connection):
        """Acquire data over the connection."""

    @abstractmethod
    def establish_connection(self):
        """Establish a connection. The connection must be a context manager."""

    @abstractmethod
    def is_connection_active(self, connection):
        """Ascertain whether the connection is active and healthy."""

    def run(self):
        is_connected = False
        with ExitStack() as exit_stack:
            while True:
                while not is_connected:
                    try:
                        connection = exit_stack.enter_context(
                            self.establish_connection()
                        )
                        is_connected = True
                    except Exception:
                        _logger.exception("failed to connect")
                        time.sleep(1)
                while True:
                    try:
                        data = self.acquire_data(connection)
                        with self.lock:
                            self.data = data
                        # FIXME: Use an interval from self.config instead.
                        time.sleep(0.1)
                    except:
                        _logger.exception("error during acquiring of data")
                        if not self.is_connection_active(connection):
                            # Force-close the connection.
                            exit_stack.close()
                            is_connected = False
                            break
                        # While connection is still active, try again.
