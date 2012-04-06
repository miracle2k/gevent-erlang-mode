import gevent
from gevent.timeout import Timeout
from nose.tools import assert_raises
from erlangmode import Mailbox
from erlangmode.mailbox import match
from base import *


class TestSend(object):
    """Adding messages to a mailbox."""

    def test(self):
        mb = Mailbox()
        mb << 5
        mb << ('bla', 'foo')
        assert mb._mailbox.get_nowait() == (None, 5)
        assert mb._mailbox.get_nowait() == (None, ('bla', 'foo'))

    def test_multi(self):
        mb = Mailbox()
        mb << 5 << 6 << 7
        assert mb._mailbox.get_nowait() == (None, 5)
        assert mb._mailbox.get_nowait() == (None, 6)
        assert mb._mailbox.get_nowait() == (None, 7)

    def test_with_responder(self):
        mb = Mailbox()
        async_result = mb | 1
        assert mb._mailbox.get_nowait() == (async_result, 1)


class TestReceive(object):
    """Test the receive construct."""

    def test_no_fallthrough(self):
        """Only one receive clause ever matches."""
        mb = Mailbox()
        mb << 'a'
        for receive in mb:
            if receive('a'):
                pass
            if receive('a'):
                raise Exception('second receive matched')
            break

    def test_break(self):
        """Test that break is needed to leave the loop.
        """
        mb = Mailbox()
        mb << 'a' << 'b' << 'c' << 'a'

        received = []
        for receive in mb:
            if receive('c'):
                received.append('c')
                break
            if receive('a'):
                received.append('a')

        # a matches first, then c, then we break.
        assert received == ['a', 'c']
        # b and the second a remain in the mailbox/savequeue
        assert mb._save_queue.qsize() == 1
        assert mb._save_queue.get_nowait() == (None, 'b')
        assert mb._mailbox.qsize() == 1
        assert mb._mailbox.get_nowait() == (None, 'a')

    def test_save_queue(self):
        mb = Mailbox()
        mb._save_queue.put((None, 'a'))
        mb << 'b' << 'c'

        received = []
        for receive in mb:
            if receive('a'):
                received.append('a')
            if receive('c'):
                received.append('c')
                break

        # a was taken from save queue, c from mailbox
        assert received == ['a', 'c']
        # b was not matched and is the new content of the save queue
        assert mb._save_queue.qsize() == 1
        assert mb._save_queue.get_nowait() ==(None, 'b')
        assert mb._mailbox.qsize() == 0

    def test_match(self):
        """Test that the ``receive`` object as the proper attributes
        after a successful match.``"""
        mb = Mailbox()
        mb << 'a'
        for receive in mb:
            if receive('a'):
                assert receive.message == 'a'
                assert receive.match == ()
                break

    def test_block(self):
        mb = Mailbox()
        gevent.spawn_later(STEP*0.5, lambda: mb << 'a')

        received = False
        for receive in mb:
            if receive('a'):
                received = True
                break

        assert received

    def test_timeout(self):
        """Test the timeout clause.
        """
        mb = Mailbox()
        gevent.spawn_later(STEP*1.5, lambda: mb << 'a')

        timed_out = False
        for receive in mb:
            if receive('a'):
                break
            if receive(timeout=STEP):
                timed_out = True
                break
        assert timed_out

    def test_total_timeout(self):
        """A timeout is meant to specify the maximum time until a message
        is received that breaks from the loop:

        Meaning:
        - Receiving a message that does not match will not reset the timeout.
        - Receiving a message that does match but which's clause does not
          break will not reset the timeout.
        """
        mb = Mailbox()
        gevent.spawn_later(STEP*0.5, lambda: mb << 'not matching')
        gevent.spawn_later(STEP*1.5, lambda: mb << 'not breaking')
        gevent.spawn_later(STEP*2.5, lambda: mb << 'match and break')

        timed_out = False
        matched = 0
        for receive in mb:
            if receive('not breaking'):
                matched += 1
            if receive('match and break'):
                matched += 1
                break
            if receive(timeout=STEP*2):
                timed_out = True
                break

        # The last matching and breaking message is coming in too late.
        assert timed_out
        assert matched == 1

    def test_zero_timeout(self):
        """Test that timeout=0 works."""
        mb = Mailbox()
        timed_out = False
        for receive in mb:
            if receive(timeout=0):
                timed_out = True
        assert timed_out

    def test_timeout_breaks(self):
        """The timeout-clause does not need an explicit break.
        """
        mb = Mailbox()
        for receive in mb:
            if receive(timeout=STEP):
                pass
        assert True

    def test_responding(self):
        """Test async result of message being processed."""
        mb = Mailbox()
        def loop():
            for receive in mb:
                if receive(object, object):
                    value, sleep = receive.match
                    gevent.sleep(sleep)
                    if value:
                        receive.respond(value*2)
                    else:
                        break
                if receive(): raise ValueError()
        gl = gevent.spawn_link_exception(loop)

        # Return a value
        assert (mb | (5, 0)).get() == 10

        # Return a value not soon enough
        assert_raises(Timeout, (mb | (5, STEP*2)).get, timeout=STEP) == 10

        # Default value is returned if respond() not explicitly called
        assert (mb | (False, 0)).get() is None

        gl.kill()

    def test_responding_implicitly(self):
        """Test hat we get a `message processed` response even if
       the receive loop does not set a value AND breaks, without calling
       the generator again.
       """
        mb = Mailbox()
        def loop():
            for receive in mb:
                if receive():
                    break
        gl = gevent.spawn_link_exception(loop)

        # Default value is returned if respond() not explicitly called
        assert (mb | (False, 0)).get() is None

        gl.kill()


class TestMatching(object):
    """Test the specific matching.
    """

    def test_different_lengths(self):
        assert match((5, 4, 'sdf'), (int, int, str, int)) is None

    def test_ident_objects(self):
        """``is`` ident check causes a match."""
        obj = object()
        assert match((obj,), (obj,)) == ()
        assert match((obj,), (object(),)) is None

    def test_equality(self):
        """== check causes a match."""
        class any(object):
            def __eq__(self, other):
                return True
        assert match((any(),), (5,)) == ()

        # Long strings do not match with ``is``.
        assert match(('abc'*1000,), ('abc'*1000,)) == ()

    def test_class_capture(self):
        """Capturing values by matching against a class pattern."""
        assert match((int,), (5,)) == (5,)
        assert match((int,), (int,)) == ()

        # Multiple matches
        assert match(('a', int, int), ('a', 5, 7)) == (5, 7)

        # object can be used to match many things
        assert match((object, object, object), (5, 'foo', {})) == (5, 'foo', {})

    def test_class_type(self):
        """Test that old-style classes work."""
        class Foo:
            pass
        foo = Foo()
        assert match((Foo,), (foo,)) == (foo,)

    def test_dict(self):
        """dicts have special handling."""

        # It's ok if message has more items than pattern
        assert match(({},), ({'foo': 'bar'},)) == ()

        # But message must have all items that pattern does
        assert match(({'foo': 'bar'},), ({},)) is None
        assert match(({'foo': 'bar'},), ({'foo': 'bar'},)) == ()

        # And those items have to match as well
        assert match(({'foo': 'bar'},), ({'foo': 'baz'},)) is None

        # Class placeholders are supported in dicts as well
        assert match(({'foo': str},), ({'foo': 'bar'},)) == ('bar',)

        # dicts can be nested
        assert match(({'spam': {'ham': str}},),
            ({'spam': {'ham': 'eggs'}},)) == ('eggs',)

    def test_catch_all(self):
        """An empty pattern means match all."""
        assert match((), (1,)) == ()
        assert match((), ('sdf', 1, 2, 3, {'a': 'b'})) == ()
