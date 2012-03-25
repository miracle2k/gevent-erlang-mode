import gevent

__all__ = ('STEP', 'step')


STEP = .1
def step():
    gevent.sleep(STEP)
