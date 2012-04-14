import gevent
import gevent.core


__all__ = ('send_after',)


if gevent.__version__ <= '0.13.6':
    # This is the old version that used libevent

    class Timer(object):
        __slots__ = ('_seconds', '_callable', '_timer')

        def __init__(self, seconds, callable):
            self._seconds, self._callable = seconds, callable
            self._schedule()

        def _schedule(self):
            if self._seconds is not None:
                self._timer = gevent.core.timer(self._seconds, self._callable)
            else:
                self._timer = None

        def cancel(self):
            if self._timer:
                self._timer.cancel()

        def reset(self):
            self.cancel()
            self._schedule()


else:
    # New gevent versions use libev
    class Timer(object):

        __slots__ = ('_seconds', '_callable', '_timer')

        def __init__(self, seconds, callable):
            self._seconds, self._callable = seconds, callable
            self._schedule()

        def _schedule(self):
            # We need to create an entirely new timer, because it seems
            # that otherwise, the timer is NOT reset between a stop() and
            # start() call.
            if self._seconds is not None:
                self._timer = gevent.get_hub().loop.timer(self._seconds)
                self._timer.start(self._callable)
            else:
                self._timer = None

        def cancel(self):
            if self._timer:
                self._timer.stop()

        def reset(self):
            # There is a self.timer again method which is based on
            # ``ev_timer_again``. However it's not realy a good fit here both
            # due to libev design (only works with a repeating timer), and
            # the gevent wrapper design, which does not allow us to set a
            # repeat value for an existing timer.
            self.cancel()
            self._schedule()


def send_after(seconds, mailbox, message):
    """After ``seconds``, add ``message`` to ``mailbox``.

    Returns a ``Timer`` object that allows the event to be canceled and reset.
    """
    if seconds is not None and not seconds >= 0:
        raise IOError(22, 'Invalid argument')
    return Timer(seconds, lambda: mailbox << message)
