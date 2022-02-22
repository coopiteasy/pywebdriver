import io
import logging
import re
import threading
import time

import serial
from flask import jsonify

from pywebdriver import app, config

ANSWER_RE = re.compile(rb"^\?(?P<status>.)|(?P<weight>\d+\.\d+)$")

values = {}
read_thread = None

_logger = logging.getLogger(__name__)


def serial_connect():
    return serial.Serial(
        port=config.get(
            "mettler_toledo_8217_driver", "port", fallback="/dev/ttyS0"
        ),
        baudrate=config.getint(
            "mettler_toledo_8217_driver", "baudrate", fallback=9600
        ),
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.SEVENBITS,
        timeout=1,
    )


# b'\x0200.000\r'
# b'\x02?A\r' → 1000001 → in motion
# b'\x02?Q\r' → 1010001 → center of zero, in motion
# b'\x02?D\r' → 1000100 → under zero
# b'\x02?B\r' → 1000010 → over capacity


def serial_reader_task():
    global values
    poll_interval = config.getfloat(
        "mettler_toledo_8217_driver", "poll_interval", fallback=0.2
    )
    try:
        with serial_connect() as ser:
            #sio = io.TextIOWrapper(io.BufferedReader(ser), encoding="ascii", newline="\r")
            #ser.read()
            poll_time = 0
            while True:
                current_time = time.perf_counter()
                sleep_time = poll_interval - (current_time - poll_time)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                poll_time = time.perf_counter()
                buffer = b""
                valid = False
                stx = False
                # ask for weight data
                ser.write(b"W")
                while True:
                    c = ser.read(1)
                    if not c:
                        # timeout
                        break
                    if c == b"\x02":
                        # start of answer
                        stx = True
                        buffer = b""
                    elif c == b"\r":
                        # end of answer
                        if not stx:
                            continue
                        valid = True
                        break
                    else:
                        buffer += c
                if not valid:
                    print("invalid")
                    continue
                match = ANSWER_RE.match(buffer)
                if match is None:
                    continue
                matchdict = match.groupdict()
                status = matchdict["status"]
                weight = matchdict["weight"]
                if weight is not None:
                    values.update({"value": float(weight), "status": "FIXED"})
                    continue
                status_byte = int.from_bytes(status, byteorder="big")
                if status_byte & 0b1:
                    # in motion
                    values.update({"status": "ACQUIRING"})
                elif status_byte & 0b110:
                    values.update({"status": "ERROR"})

                #try:
                #    pos = buffer.index("\r\n")
                #except ValueError:
                #    continue
                #print(line)
                #buffer = buffer[:pos]
                #matches = re.match(
                #    r"^S (?P<stability>[SD])( )*(?P<weight>(-)?([0-9\.]+))( )*kg",
                #    buffer[:pos],
                #)
                #if matches:
                #    buffer = ""
                #    groups = matches.groupdict()
                #    stability = groups["stability"]
                #    value = float(groups["weight"])
                #    status = "FIXED" if stability == "S" else "ACQUIRING"
                #    values.update({"value": value, "status": status})
                #elif "kg" in buffer or len(buffer) > 128:
                #    # reset buffer we maybe have a partial value into the buffer
                #    buffer = ""
    except Exception as e:
        _logger.exception("Unable to get data from serial")
        values.update({"value": str(e), "status": "ERROR"})
        raise e


@app.before_first_request
def start_read_thread_job():
    global read_thread
    read_thread = threading.Thread(target=serial_reader_task)
    read_thread.daemon = True
    read_thread.start()


@app.before_request
def check_read_thread_alive_job():
    global read_thread
    if not read_thread or not read_thread.is_alive():
        start_read_thread_job()


@app.route("/hw_proxy/weight", methods=["GET"])
def serial_read_http():
    return jsonify(**values)


@app.route("/hw_proxy/scale_read", methods=["POST"])
def serial_read_http_post():
    return jsonify(
        jsonrpc="2.0",
        result={
            "weight": values["value"],
            "unit": "kg",
            "info": "ok",
        },
    )
