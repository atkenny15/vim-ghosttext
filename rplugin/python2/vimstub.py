import copy
import readline
import logging

class Vim(object):
    def __init__(self):
        self.buffers = [Buffer()]
        self.current = self.buffers[0]

    def command(self, cmd):
        logging.info('vim.command(%s)', cmd)

class Buffer(object):
    def __init__(self):
        self.buffer = ['init']

vim = Vim()
