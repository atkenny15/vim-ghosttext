#!/usr/bin/env python
#
# Uber, Inc. (c) 2017
#

"""
Module docstring documenting the usage of the command line interface (CLI).
"""

from __future__ import absolute_import
from __future__ import print_function
import argparse
import sys
import os
import re
import time
import json
import signal
import socket
import random
import threading
import hashlib
import base64
import textwrap
import tempfile

try:
    import readline
except:
    pass

import logging

try:
    import vim
except:
    from vimstub import vim

import subprocess
import BaseHTTPServer

#--------------------------------------------------
# Frame
#--------------------------------------------------

class Frame(object):
    TEXT = 1
    CLOSE = 8

    def __init__(self, data=None, fin=1, opcode=TEXT, payload=None, mask=0, mask_key=0x0):
        self.data = data

        # User settable
        self.fin = fin
        self.opcode = opcode
        self.payload = payload
        self.mask_key = mask_key
        self.mask = mask

        # Internally controlled
        if self.payload is None:
            self.payload = bytearray()
        self.payload_len = len(self.payload)

        self.closed = False

        if self.data is not None:
            self._parse()
        else:
            self._set_data()

    def _parse(self):
        data = self.data

        self.fin = bool(data[0] & 0x80)
        self.opcode = data[0] & 0x0f

        self.mask = bool(data[1] & 0x80)
        self.payload_len = data[1] & 0x7f

        next_byte = 2
        if self.payload_len == 126:
            self.payload_len = 0
            for i in range(2):
                self.payload_len = (self.payload_len << 8) | data[i + next_byte]
            next_byte = next_byte + i + 1
        elif self.payload_len == 127:
            for i in range(8):
                self.payload_len = (self.payload_len << 8) | data[i + next_byte]
            next_byte = next_byte + i + 1

        if self.mask:
            self.mask_key = 0
            for i in range(4):
                self.mask_key = self.mask_key | (data[i + next_byte] << (8 * i))
            next_byte = next_byte + i + 1

        self.payload = data[next_byte:]
        if self.opcode == Frame.TEXT:
            unmasked = bytearray()
            for i in range(self.payload_len):
                j = i % 4
                incoming_octet = self.payload[i]
                mask_octet = (self.mask_key >> (j * 8)) & 0xff
                unmasked.append(incoming_octet ^ mask_octet)
            self.payload = unmasked
        elif self.opcode == Frame.CLOSE:
            self.closed = True
        else:
            raise Exception(self.opcode)

    def _set_data(self):
        self.data = bytearray()

        self.data.extend([
            ((self.fin & 0x1) << 7) | (self.opcode & 0xf),
        ])

        if self.payload_len >= 126:
            if self.payload_len < (1 << 16):
                self.data.append(((self.mask & 0x1) << 7) | 0x7e)
                for i in reversed(range(2)):
                    self.data.append((self.payload_len >> (i * 8)) & 0xff)
            else:
                self.data.append(((self.mask & 0x1) << 7) | 0x7f)
                for i in reversed(range(8)):
                    self.data.append((self.payload_len >> (i * 8)) & 0xff)
        else:
            self.data.append(((self.mask & 0x1) << 7) | (self.payload_len & 0x7f))

        if self.mask:
            if self.mask_key is None:
                raise Exception("Missing mask key")
            raise Exception("TODO")
        
        self.data.extend(self.payload)

    def __str__(self):
        string = textwrap.dedent("""
            Fin:         %s
            Closed:      %s
            Opcode:      %x
            Mask:        %s
            Mask Key:    %08x
            Payload Len: %s
            Payload:     %s
        """) % (
            self.fin,
            self.closed,
            self.opcode,
            self.mask,
            self.mask_key,
            self.payload_len,
            self.payload.decode('utf-8'),
        )
        return string.encode('utf-8')

#--------------------------------------------------
# WebSocket
#--------------------------------------------------

class WebSocketServer(object):
    def __init__(self, port, lock, done, to_thread, from_thread):
        self.port = port
        self._sock = None
        self._conn = None
        self._addr = None

        # Lock for accessing Vim
        self._vim_lock = lock

        # This socket is valid (received data from GhostText after handshake)
        self.valid = False

        # Event from the HTTP server to finish (HTTP server is shutting down),
        # this is sent to all threads and should not be cleared
        self._done = done

        # Indicates that data is available from Vim and that the thread has
        # finished processing the data
        self._to_thread = to_thread
        self._from_thread = from_thread

        logging.info("Starting websocket on port %d", self.port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('localhost', port))
        self._sock.listen(5)

    def __del__(self):
        logging.info("Cleaning up websocket")

    def serve_forever(self):
        logging.info("Serving")
        self._conn, self._addr = self._sock.accept()
        logging.info("Accepted connection")
        self._handshake()
        logging.info("Handshake finished")

        loop = 0
        update = time.time()
        while not self._done.is_set():
            loop = loop + 1

            if time.time() - update >= 3:
                update = time.time()
                logging.info("Running...")

            # Check for data from socket
            recv = None
            if loop == 1:
                # GhostText launches a bunch of websockets sometimes, and does
                # the handshake but only communicates on a single one after
                # that. For any threads that do not receive data within 3s,
                # stop them
                recv = self._recv(timeout=3)

                if recv is None:
                    logging.info("Timeout while waiting for data on first loop")
                    # Socket is closed at the end of this function
                    break

                # Indicate this socket is valid (for setting the event in GhostNotify)
                self.valid = True
            else:
                recv = self._recv(block=False)

            # If data was received on the socket
            if recv is not None:
                frame = Frame(data=bytearray(recv))
                logging.debug("Received: '%s'", str(frame))

                if frame.closed:
                    # If the server indicated to close the socket via a close
                    # frame
                    self._vim_lock.acquire()
                    logging.info('GhostText closed the connection')
                    vim.command('echo "GhostText closed the connection, try re-loading the webpage if this was unexpected"')
                    self._vim_lock.release()
                    self._conn.close()
                    self._conn = None
                    break
                else:
                    # Otherwise send data to Vim
                    logging.info("Data received")
                    self._update_to_vim(frame.payload.decode('utf-8'))

            # Check to see if GhostNotify was called
            if self._to_thread.is_set():
                # Reset event flag
                self._to_thread.clear()

                # Get data from Vim and send it to GhostText
                logging.info("Event set")
                self._update_from_vim()

                # Tell GhostNotify to quit blocking
                logging.info("Thread done")
                self._from_thread.set()

            if not self.valid:
                break

            time.sleep(0.001)

        logging.info("Done serving")
        if self._conn is not None:
            # Send close frame
            self._conn.sendall(Frame(opcode=Frame.CLOSE).data)
            self._conn.close()
            self._conn = None

    def _update_from_vim(self):
        logging.info("Getting data from vim, waiting for lock")
        self._vim_lock.acquire()
        logging.info("Lock acquired")

        lines = vim.current.buffer[:]

        self._vim_lock.release()
        logging.info("Released lock")
        text = '\n'.join(lines)
        self._send_text(text)

    def _send_text(self, text):
        data = {
            'text': text,
            'selections': [{'start': len(text), 'end': len(text)}],
            'title': 'ghosttext-vim',
            'url': '',
            'syntax': '',
        }

        logging.debug("Sending: '%s'", data)

        frame = Frame(fin=1, opcode=Frame.TEXT, mask=0, payload=bytearray(json.dumps(data)))
        logging.debug("Sending: '%s'", str(frame))
        self._conn.sendall(frame.data)

    def _update_to_vim(self, string):
        request = json.loads(string)

        logging.info("Sending data to vim, waiting for lock")
        self._vim_lock.acquire()
        logging.info("Lock acquired")

        vim.command('autocmd! TextChanged,TextChangedI * python GhostNotify()')
        vim.current.buffer[:] = request['text'].split('\n')
        vim.command('checktime')
        vim.command('autocmd TextChanged,TextChangedI * python GhostNotify()')

        self._vim_lock.release()
        logging.info("Released lock")

    def _handshake(self):
        msg = self._recv()

        rx = re.compile('^Sec-WebSocket-Key:\s+(\S+)\s*$', re.M)
        match = rx.search(msg)
        if not match:
            raise
        logging.debug('key = %s', match.group(1))
        accept = self.__class__._get_accept(match.group(1))
        logging.debug('accept = %s', accept)

        send = str(
            "HTTP/1.1 101 Switching Protocols\r\n" +
            "Upgrade: websocket\r\n" +
            "Connection: Upgrade\r\n" +
            "Sec-WebSocket-Accept: " + accept + "\r\n\r\n")
        logging.debug(send)
        self._conn.sendall(send)

    def _recv(self, buf_len=4096, timeout=None, sleep=0.1, block=True):
        msg = None
        while True:
            string = None
            if timeout is not None:
                string = self._recv_timeout(buf_len, timeout, sleep)
                if string is None:
                    break
            elif not block:
                try:
                    self._conn.setblocking(0)
                    string = self._conn.recv(buf_len)
                    self._conn.setblocking(1)
                except socket.error as e:
                    if e.errno == 11:
                        pass
                    elif e.errno == 10035:
                        pass
                    else:
                        raise
                if string is None:
                    #logging.debug("Exception")
                    msg = None
                    break
                elif len(string) == 0:
                    #logging.debug("No data")
                    msg = None
                    break
            else:
                string = self._conn.recv(buf_len)
            if msg is None:
                msg = ''
            msg = msg + string
            if len(string) < buf_len:
                break
        return msg

    def _recv_timeout(self, buf_len, timeout, sleep):
        msg = None
        prev = None
        start_time = time.time()
        while True:
            if time.time() - start_time >= timeout:
                msg = None
                break

            ret = ''
            try:
                self._conn.setblocking(0)
                ret = self._conn.recv(buf_len)
                self._conn.setblocking(1)
            except socket.error as e:
                if e.errno == 11:
                    pass
                elif e.errno == 10035:
                    pass
                else:
                    raise

            if len(ret):
                if msg is None:
                    msg = ret
                else:
                    msg = msg + ret
                prev = ret
            elif prev:
                break

            time.sleep(sleep)

        return msg

    @staticmethod
    def _get_accept(string):
        sha = hashlib.sha1()
        sha.update(string + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
        accept = base64.b64encode(sha.digest())
        return accept

    @staticmethod
    def startwebsocket(port, lock, done, to_thread, from_thread):
        websocketserver = WebSocketServer(port, lock, done, to_thread, from_thread)
        thread = threading.Thread(target=websocketserver.serve_forever)
        thread.daemon = False
        thread.start()
        return websocketserver

#--------------------------------------------------
# HTTP Server
#--------------------------------------------------

class WebRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def do_GET(self):
        self._set_headers()
        port = random.randint(60000, 65535)
        response_obj = {
            "ProtocolVersion": 1,
            "WebSocketPort": port,
        }
        logging.info("Handling HTTP request, starting websocket on port %d", port)

        to_thread = threading.Event()
        from_thread = threading.Event()
        sock = WebSocketServer.startwebsocket(port, self.server.vim_lock, self.server.done, to_thread, from_thread)
        self.server.websocks.append({'sock': sock, 'to_thread': to_thread, 'from_thread': from_thread})

        logging.info("Websocket started on port %d", port)
        self.wfile.write(json.dumps(response_obj).encode())

    def log_message(self, format, *args):
        logging.info(format, *args)
        self.server.vim_lock.acquire()
        vim.command('echo "Connection received from GhostText"')
        self.server.vim_lock.release()

class MyHTTPServer(BaseHTTPServer.HTTPServer, object):
    def __init__(self, *args, **kwargs):
        super(MyHTTPServer, self).__init__(*args, **kwargs)
        if hasattr(self, 'vim_lock'):
            raise
        if hasattr(self, 'websocks'):
            raise
        self.vim_lock = threading.Lock()
        self.done = threading.Event()
        self.websocks = []

#--------------------------------------------------
# Main
#--------------------------------------------------

HTTPSERVER = None

def GhostStart():
    global HTTPSERVER
    if HTTPSERVER is None:
        HTTPSERVER = MyHTTPServer(('localhost', 4001), WebRequestHandler)

        thread = threading.Thread(target=HTTPSERVER.serve_forever)

        # Do not close script until the HTTP server is done
        thread.daemon = False
        thread.start()

        HTTPSERVER.vim_lock.acquire()
        vim.command('echo "Starting server"')
        logging.info("Starting HTTP server")
        vim.command('autocmd VimLeave * GhostStop')
        vim.command('autocmd TextChanged,TextChangedI * python GhostNotify()')
        HTTPSERVER.vim_lock.release()
    else:
        vim.command('echo "Server is already running"')

def GhostStop():
    global HTTPSERVER
    if HTTPSERVER is None:
        vim.command('echo "Server is not running"')
    else:
        HTTPSERVER.vim_lock.acquire()
        vim.command('echo "Stopping server"')
        vim.command('autocmd! VimLeave * GhostStop')
        HTTPSERVER.vim_lock.release()

        logging.info("Stopping threads")
        HTTPSERVER.done.set()
        logging.info("Stopping HTTP server")
        HTTPSERVER.shutdown()
        HTTPSERVER = None

def GhostNotify():
    global HTTPSERVER
    if HTTPSERVER is None:
        vim.command('echo "Server is not running"')
    else:
        logging.info("GhostNotify update")
        found = 0
        wait = []
        for ws in HTTPSERVER.websocks:
            # Indicate to the valid websockets that there is data ready in Vim
            if ws['sock'].valid:
                if ws['to_thread'].is_set():
                    logging.error("To event is already set")
                if ws['from_thread'].is_set():
                    logging.error("From event is already set")
                found = found + 1
                if found:
                    logging.info("Setting event")
                    ws['to_thread'].set()
                    wait.append(ws)

        for ws in wait:
            logging.info("Waiting for thread completion")
            ws['from_thread'].wait()
            logging.info("Thread done")
            ws['from_thread'].clear()

        if found == 0:
            logging.error("No valid websockets found")
        if found > 1:
            logging.error("Multiple valid websockets found")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run', default=False, action='store_true', help='run from commandline')
    args = parser.parse_args(sys.argv[1:])

    temp_fn = os.path.join(tempfile.gettempdir(), 'ghosttext-vim-log.txt')
    try:
        os.remove(temp_fn)
    except OSError as e:
        if e.errno == 2:
            # OSError: [Errno 2] No such file or directory
            pass
        else:
            raise

    logging.basicConfig(format='[ %(levelname)-5s %(asctime)s %(threadName)s ] %(message)s', filename=temp_fn, level=logging.INFO)
    logging.info("Starting script...")

    # This runs the script without Vim to make debugging easier, input comes
    # from the terminal
    if args.run:
        GhostStart()

        done = [False]
        def handler(signum, frame):
            done[0] = True

        signal.signal(signal.SIGINT, handler)

        while not done[0]:
            lines = []
            while not done[0]:
                try:
                    string = raw_input('> ')
                except EOFError:
                    print()
                    break
                lines.append(string)
            if not done[0]:
                vim.current.buffer[:] = lines[:]
                GhostNotify()
        print()

        signal.signal(signal.SIGINT, signal.SIG_DFL)

        GhostStop()
