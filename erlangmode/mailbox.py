"""Implements Erlang-style mailboxes, on top of GEvent.

Sending messages happens via the bitwise ``shift left`` operator::

    process = Mailbox()
    process << 5
    process << (True, 5)
    process << dict(command='exit')
    process << 'reload', {'timeout': 5}

.. note:

   An alternative syntax that could have been used is the bitwise ``or``
   operator::

        process | 5


Matching messages in the mailbox::

    mailbox = Mailbox()
    mailbox << 5, 2
    for receive in mailbox:
        if receive(int, int):
            a, b = receive.match
            break

Notice the ``break`` in the above example. The semantics are not identical to
Erlang: In Erlang, after a single clause matches, the receive statement ends,
and if you want to match multiple messages, you use a function that calls
itself recursively again and again. Since Python does not support this kind
of infinite tail recursion, the loop will instead run until you break out of
it yourself.

So specifically, the process is:

1) Match the first message against the first receive(), then against the
   second and so on, until one clause matches.
2) If a receive does match, the message is removed from the mailbox.
3) Otherwise it will be kept, and the next time the mailbox is iterated, the
   message will again be matched against every receive().
4) Match the second message against all receive() clauses.
5) If all messages in the mailbox have been processed (either removed or
   unmatched), block the greenlet until new messages arrive, or the timeout
   triggers.


Matching is rather full featured. If a class is given, an instance of the
class is expected. Other values needs to match exactly::

    if receive('sum', int, int):
        assert receive.match == (5, 2)
        assert receive.message == ('sum', 5, 2)

As you can see, ``message`` returns the original message, the ``match``
attribute only those values that have been captured by passing a placeholder
(i.e. a class).

Recursive matching is also supported::

     if receive({'values': (2, int)}):
        assert receive.message == {'values': (2, 42)}
        assert receive.match == 42

``match`` will be a single value if only a single placeholder was in the
receive clause, or it will be a tuple if there are multiple placeholders.

.. note::
    Note that the above becomes problematic when you have multiple keys in the
    dict with placeholders. Since a ``dict`` in Python has no defined order,
    the order of the captured values in ``match`` will also be undefined.

Finally, with ``gevent``, timeouts are supported::

    for receive in mailbox:
        if receive(int, int):
            return 'success', a+b
        if receive(timeout=5):
            return 'error', 'timeout'

The timeout clause must be the last one, and only one timeout clause can exist
(both restrictions are enforced).


There is a catch-all receive, that in combination with the timeout can be used
to clear the mailbox::

    for receive in mailbox:
        if receive():  # Will always match
            pass
        if receive(timeout=0):
            break


PEP 377
=======

This would have allowed a context manager to skip the statement body, allowing
for a nicer receive syntax using ``with`` instead of ``if``::

    for receive in mailbox:
        with receive('sum', int, int, object) as (a, b, sender):
            sender << a + b
            break

It would also make the code easier by giving us a hook after the ``break``.

Unfortunately, the proposal was rejected.

http://www.python.org/dev/peps/pep-0377/
"""

import time
from gevent.queue import Queue, Empty


__all__ = ('Mailbox',)


# Special message value being passed around for timeout support.
class TIMEOUT(object):
    __slots__ = ['run', 'seconds']
    def __init__(self, run=False):
        self.run = run
        self.seconds = None


class Matcher(object):
    """Helper that matches a wrapped message against a clause.

    An instance of this is what you'll have in ``receive``.
    """

    def __init__(self, message):
        self.message = message
        self._consumed = False

    def __call__(self, *args, **kwargs):
        timeout_seconds = kwargs.pop('timeout', None)
        assert not kwargs, 'Unsupported kwarg given: %s' % kwargs.keys()[0]

        # Never match two clauses.
        if self._consumed:
            return False

        if timeout_seconds is not None:
            assert not args, 'The timeout-clause may not attempt to '\
                'match against the message'

            if not isinstance(self.message, TIMEOUT):
                # The timeout matcher only reacts to a special TIMEOUT value
                # being passed down, ignores everything else.
                return False

            timeout = self.message

            # Mailbox tells us that we should run the timeout clause:
            if timeout.run:
                return True

            # Otherwise, we need to tell Mailbox about the timeout value used.
            assert timeout.seconds is None,\
                'Only one timeout-clause can be used.'
            timeout.seconds = timeout_seconds
            # Don't match the clause yet.
            return False
        else:
            # Ignore our special timeout messages
            if isinstance(self.message, TIMEOUT):
                return False

            if args == (self.message,):
                self.match = None
                self._consumed = True
                return True
            return False


class Mailbox(object):
    """Implements an Erlang-like mailbox.
    """

    def __init__(self):
        self._mailbox = Queue()
        self._save_queue = Queue()
        self._old_save_queues = []

    def __lshift__(self, other):
        self.receive_message(other)
        return self

    def receive_message(self, message):
        self._mailbox.put(message)

    def __iter__(self):
        # Install a new save queue. We need to have a list of those, because
        # we cannot run any code after a ``break``. Thus, we cannot be sure
        # that this __iter__ will even empty the current save queue fully.
        self._old_save_queues.insert(0, self._save_queue)
        self._save_queue = Queue()

        # Returns the first non-empty save_queue, cleans out empty save
        # queues, returns mailbox if all save_queues empty.
        def queue():
            while self._old_save_queues:
                q = self._old_save_queues[0]
                if not q.empty():
                    return q
                del self._old_save_queues[0]
            return self._mailbox

        timeout = None
        timeout_used = 0
        while True:
            try:
                message = queue().get_nowait()
            except Empty:
                # The first time we need the timeout, yield a matcher with a
                # special internal value. If there is a clause that defines
                # a timeout (the matcher being called with a timeout value),
                # then we will know when we return.
                if not timeout:
                    timeout = TIMEOUT()
                    yield Matcher(timeout)

                # Try again with a timeout:
                start = time.time()
                try:
                    block = True
                    actual_timeout = max(timeout.seconds - timeout_used, 0) \
                        if timeout.seconds is not None else None
                    if actual_timeout == 0:
                        block = False
                        actual_timeout = None
                    message = queue().get(timeout=actual_timeout, block=block)
                except Empty:
                    # Timeout failed, run the timeout clause, by handing
                    # down a special object.
                    assert timeout.seconds is not None
                    yield Matcher(TIMEOUT(run=True))
                    # And we are done.
                    return
                else:
                    timeout_used += (time.time() - start)
                    print timeout_used

            # Hand down the message
            matcher = Matcher(message)
            yield matcher
            if not matcher._consumed:
                # Remember for the next time the mailbox is iterated.
                self._save_queue.put(message)




