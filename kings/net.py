from .objects import Db, Player
import gevent.queue
import gevent.socket
from gevent.server import StreamServer

from .common import *

class MUD(object):
    @classmethod
    def init(cls, config):
        cls.db = Db.init(config)
        return cls(config.get('kings', 'bind_address'), config.getint('kings', 'port'))

    def __init__(self, address, port):
        self.address = address
        self.port = port

    def run(self):
        log.info('Listening at {0}:{1}'.format(self.address, self.port))
        self.server = StreamServer((self.address, self.port), connect)
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            log.info("Received KeyboardInterrupt, exiting")

class NoInput(Exception): pass

# Runs in its own greenlet
def connect(socket, address):
    log.info('New connection from %s:%s' % address)
    conn = socket.makefile()
    conn.write("User: ")
    conn.flush()
    username = conn.readline().strip()

    # FIXME: add auth
    player = Player.init(oid=username, location_oid="town_square")

    player.running = True
    prompt = "\n% "
    conn.write(player.look(player.location()) + prompt)
    conn.flush()
    try:
        while player.running:
            try:
                gevent.socket.wait_read(conn.fileno(), timeout=0.01, timeout_exc=NoInput())
            except NoInput:
                pass
            else:
                line = conn.readline().strip()
                if line:
                    player.interpret(line)
            try:
                messages = player.messages.get(block=True, timeout=0.01)
                conn.write('\n'.join(messages + ["% "]))
                conn.flush()
            except gevent.queue.Empty:
                pass
    finally:
        log.info("client disconnected")
        player.close()

