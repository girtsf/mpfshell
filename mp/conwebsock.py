##
# The MIT License (MIT)
#
# Copyright (c) 2016 Stefan Wendler
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
##


import websocket
import threading
import time
import logging

from collections import deque
from mp.conbase import ConBase, ConError


class ConWebsock(ConBase, threading.Thread):

    def __init__(self, ip, password):

        ConBase.__init__(self)
        threading.Thread.__init__(self)

        self.daemon = True

        # List of strings, data received from websocket but yet to be
        # processed.
        self.fifo = deque()
        # Signal that there is new data available. When incoming messages arrive over
        # websocket, we notify on this condition variable.
        self.fifo_has_data = threading.Condition()

        websocket.enableTrace(logging.root.getEffectiveLevel() < logging.INFO)

        self.ip = ip
        self.password = password
        self.ws = websocket.WebSocketApp("ws://%s:8266" % ip,
                                         on_open=self.on_open,
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close)

        self.start()
        self.authenticate()

    def on_open(self, ws):
        """Called when we connect to the websocket server."""
        logging.debug("websocket on_open()")

    def authenticate(self):
        self.timeout = 5.0
        # Authenticate.
        self.wait_for_string("Password: ")
        self.ws.send(self.password + "\r")
        self.wait_for_string("WebREPL connected")
        self.timeout = 1.0

        logging.info("websocket connected to ws://%s:8266" % self.ip)

    def wait_for_string(self, string):
        """Reads data until we see a given string or reach timeout."""
        data = ""

        tstart = time.time()

        while True:
            with self.fifo_has_data:
                elapsed_time = time.time() - tstart
                remaining_time = self.timeout - elapsed_time
                if remaining_time < 0:
                    raise ConError("Timed out waiting for '%s'" % string)
                if self.fifo:
                    # If there is data in the fifo, append it to data string.
                    data += self.fifo.popleft()
                    # See if out string shows up.
                    if string in data:
                        # It does, put stuff after the string back in the deque.
                        _, after = data.split(string, 1)
                        self.fifo.appendleft(after)
                        return
                else:
                    self.fifo_has_data.wait(remaining_time)

    def run(self):
        self.ws.run_forever()

    def __del__(self):
        self.close()

    def on_message(self, ws, message):
        with self.fifo_has_data:
            self.fifo.append(message)
            self.fifo_has_data.notify_all()

    def on_error(self, ws, error):
        logging.error("websocket error: %s" % error)
        with self.fifo_has_data:
            self.fifo_has_data.notify_all()

    def on_close(self, ws):
        logging.info("websocket closed")
        with self.fifo_has_data:
            # TODO: we might want to set a flag here so that the reader can
            # exit.
            self.fifo_has_data.notify_all()

    def close(self):
        try:
            self.ws.close()
        finally:
            with self.fifo_has_data:
                self.fifo_has_data.notify_all()

    def read(self, size=1):
        """Reads up to size (or timeout), returns bytes."""
        # List of strings, joined together at the end for efficiency.
        data = []

        tstart = time.time()

        while len(data) < size:
            with self.fifo_has_data:
                elapsed_time = time.time() - tstart
                remaining_time = self.timeout - elapsed_time
                if remaining_time < 0:
                    break
                if self.fifo:
                    # If there is data in the fifo, grab it.
                    data.append(self.fifo.popleft())
                else:
                    # If there is no data in fifo yet, but we have not
                    # reached timeout yet, wait. We will get woken
                    # up if new data arrives.
                    self.fifo_has_data.wait(remaining_time)

        return ''.join(data).encode("utf-8")

    def write(self, data):

        self.ws.send(data)
        return len(data)

    def inWaiting(self):
        return len(self.fifo)

    def survives_soft_reset(self):
        return False
