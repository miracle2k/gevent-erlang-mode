import gevent.core


__all__ = ('send_after',)



class Timer(object):

    __slots__ = ('_seconds', '_callable', '_timer')

    def __init__(self, seconds, callable):
        self._seconds, self._callable = seconds, callable
        self._schedule()

    def _schedule(self):
        self._timer = gevent.core.timer(self._seconds, self._callable)

    def cancel(self):
        self._timer.cancel()

    def reset(self):
        self._timer.cancel()
        self._schedule()


def send_after(seconds, mailbox, message):
    """After ``seconds``, add ``message`` to ``mailbox``.

    Returns a ``Timer`` object that allows the event to be canceled and reset.
    """
    if not seconds >= 0:
        raise IOError(22, 'Invalid argument')
    return Timer(seconds, lambda: mailbox << message)
