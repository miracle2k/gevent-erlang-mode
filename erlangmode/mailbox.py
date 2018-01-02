"""Implements Erlang-style mailboxes, on top of GEvent.

Sending messages happens via the bitwise ``shift left`` operator::

    process = Mailbox()
    process << 5
    process << (True, 5)
    process << dict(command='exit')
    process << 'reload', {'timeout': 5}
    process << 1 << 2 << 3


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


A thing that Erlang cannot do: Since we have shared state, you can receive an
immediate result from the message processor::

    result = mailbox | 5
    result.get()

``result`` is a ``gevent`` ``ASyncResult`` instance. By using ``|`` instead of
``<<`` you will get such an object. ``get()`` blocks the current greenlet until
the message has been processed. The return value will be ``None``, or a value
set by the mailbox processor::

    for receive in mailbox:
        if receive(str):
            receive.respond('Hello, %s' % receive.message)

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
import types
from gevent.event import AsyncResult
from gevent.queue import Queue, Empty


__all__ = ('Mailbox', 'Actor', 'Matcher', 'MessageReceiver')


# Special message value being passed around for timeout support.
class TIMEOUT(object):
    __slots__ = ['run', 'seconds']
    def __init__(self, run=False):
        self.run = run
        self.seconds = None


class Matcher(object):
    """Helper that matches a wrapped message against a clause.

    An instance of this is what you'll get when iterating over a mailbox.
    However, you may also be interested in using this class manually if you
    want to do message matching in a different way::

        match = Matcher(message)
        if match('a'):
            pass
    """

    def __init__(self, message):
        self.message = message
        self._consumed = False
        self._response = None

    def __call__(self, *args, **kwargs):
        timeout_seconds = kwargs.pop('timeout', None)
        assert not kwargs, 'Unsupported kwarg given: %s' % kwargs.keys()[0]

        # Never match two clauses.
        if self._consumed:
            return False

        # If this call defines the timeout clause...
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

        # This call is a regular match attempt...
        else:
            # Ignore our special timeout messages
            if isinstance(self.message, TIMEOUT):
                return False

            groups = match(args, tuplify(self.message))
            if not groups is None:
                self.match = groups
                self._consumed = True
                return True
            return False

    @property
    def is_active(self):
        """True if this matcher is matching against a real message,
        as opposed to internal loop-runs of this module.

        Checking this allows complicated use-cases, such as:

            for receive in mailbox:
                if receive():
                    pass

                if receive.is_active:
                    print('just processed a message')
        """
        return not isinstance(self.message, TIMEOUT)

    def respond(self, value):
        self._response = value
        self._consumed = True


class MessageReceiver(object):

    def __lshift__(self, other):
        """<< syntax to add a message to the mailbox::

            mailbox << 1 << 2 << 3
        """
        self.receive_message(other)
        return self

    def __or__(self, other):
        """| syntax to add a message to a mailbox and get an ``ASyncResult``
        instance that triggers when the message has been processed::

            result = mailbox | 1
            result.get()
       """
        result = AsyncResult()
        self.receive_message(other, responder=result)
        return result

    def receive_message(self, message, responder=None):
        raise NotImplementedError()


class Mailbox(MessageReceiver):
    """Implements an Erlang-like mailbox.
    """

    def __init__(self):
        self._mailbox = Queue()
        self._save_queue = Queue()
        self._old_save_queues = []

    def receive_message(self, message, responder=None):
        self._mailbox.put((responder, message))

    def __iter__(self):
        """The design challenge is this: In order to be able to trigger the
        ``ASyncResult`` event for a message being processed, as we might have
        to if a ``responder`` is set, even if the user does not explicitly sets
        a value, we need a way to run code after the yield. Here are the
        options:

        1) If PEP 377 had been accepted, we could use the ``with`` statement,
           and could could run in __exit__. Alas, this is not the case.

        2) try....finally could be used. However, finally in iterators is
           peculiar, and has I understand it, should the generator not be
           immediately garbage collected (a global variable, circular
           reference), then the time at which ``finally`` is executed would be
           undefined.

        3) Remove the need/support for an explicit ``break``. Then, we can
           always expect the generator to return after a yield, until such time
           that we exit manually (like after the first match). However,
           NOT stopping the loop after a match is one of the modes we want to
           support, and for performance, to do so without rematching already
           dismissed messages (otherwise, putting everything inside a ``while``
           loop might suffice). A possible approach would be to define a
           separate ``.all`` iterator::

                for receive in mailbox:
                    if receive():
                        pass  # stop automatically after a match

                for receive in mailbox.all:
                    if receive():
                        pass  #  does not stop after a match
        """

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
                responder, message = queue().get_nowait()
            except Empty:
                # The first time we need the timeout, yield a matcher with a
                # special internal value. If there is a timeout-clause, then
                # it will match this special value and tell us what the
                # timeout is.
                if not timeout:
                    timeout = TIMEOUT()
                    yield Matcher(timeout)

                # We now know the timeout value, the matcher wrote it to
                # the special object we passed down.
                start = time.time()
                try:
                    # TODO: How about using a `Timeout` instead of this arithmetic.
                    block = True
                    actual_timeout = max(timeout.seconds - timeout_used, 0) \
                        if timeout.seconds is not None else None
                    if actual_timeout == 0:
                        block = False
                        actual_timeout = None
                    responder, message = queue().get(timeout=actual_timeout, block=block)
                except Empty:
                    # Read timed out. To run the timeout clause, we
                    # yield a special object, which the timeout matcher
                    # will trigger on.
                    assert timeout.seconds is not None
                    yield Matcher(TIMEOUT(run=True))
                    # And we are done.
                    return
                else:
                    timeout_used += (time.time() - start)

            try:
                # Hand down the message
                matcher = Matcher(message)
                yield matcher
            finally:
                if not matcher._consumed:
                    # Remember for the next time the mailbox is iterated.
                    self._save_queue.put((responder, message))
                elif responder:
                    responder.set(matcher._response)



tuplify = lambda v: v if isinstance(v, tuple) else (v,)


def match(pattern, message):
    """Match ``message`` against ``pattern``, returns either ``None``
    if no match, or a list of matched classes.
    """
    assert isinstance(pattern, tuple) and isinstance(message, tuple)

    # Indicates "match all".
    if pattern == ():
        return ()

    if len(pattern) != len(message):
        return None

    groups = []
    for p, m in zip(pattern, message):
        if isinstance(p, (types.ClassType, type)):
            if isinstance(m, p):
                groups.append(m)
                continue
        if p is m:
            continue
        if p == m:
            continue
        if isinstance(p, dict) and isinstance(m, dict):
            for key, value in p.items():
                if not key in m:
                    break
                g = match(tuplify(value), tuplify(m[key]))
                if g is None:
                    break
                groups.extend(g)
            else:
                continue

        # A pair did not match, so the whole match fails.
        return None

    return tuple(groups)


class Actor(MessageReceiver):
    """An object that can be sernt messages directly (using the << and |
    operators, but exposes them via a ``mailbox`` attribute.
    """

    def __init__(self):
        self.mailbox = Mailbox()

    def receive_message(self, message, responder=None):
        self.mailbox.receive_message(message, responder)
