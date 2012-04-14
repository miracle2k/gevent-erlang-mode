import gevent


__all__ = ('LinkedFailed', 'spawn_and_link')


class LinkedFailed(Exception):
    """Raised when a linked greenlet dies because of unhandled exception"""

    msg = "%r failed with %s: %s"

    def __init__(self, source):
        exception = source.exception
        try:
            excname = exception.__class__.__name__
        except:
            excname = str(exception) or repr(exception)
        Exception.__init__(self, self.msg % (source, excname, exception))


def spawn_and_link(func):
    """Spawn as a greenlet, and link to current greenlet.

    If the spawned greenlet exits abnormally (with an exception), then a
    ``LinkedFailed`` exception will be raised in the linked greenlet.

    Gevent used to have this functionality built in, but it was removed:
    https://groups.google.com/d/topic/gevent/gZF5HcR1VqI/discussion
    """
    parent = gevent.getcurrent()
    g = gevent.spawn(func)
    g.link_exception(receiver=lambda failed: gevent.kill(parent, LinkedFailed(failed)))
    return g

