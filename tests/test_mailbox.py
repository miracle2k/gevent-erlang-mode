import gevent
from erlangmode import Mailbox
from base import *


def test_send():
    mb = Mailbox()
    mb << 5
    mb << ('bla', 'foo')
    assert mb._mailbox.get_nowait() == 5
    assert mb._mailbox.get_nowait() == ('bla', 'foo')


def multi_send():
    mb = Mailbox()
    mb << 5 << 6 << 7
    assert mb._mailbox.get_nowait() == 5
    assert mb._mailbox.get_nowait() == 6
    assert mb._mailbox.get_nowait() == 7


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
        assert mb._save_queue.get_nowait() == 'b'
        assert mb._mailbox.qsize() == 1
        assert mb._mailbox.get_nowait() == 'a'

    def test_save_queue(self):
        mb = Mailbox()
        mb._save_queue.put('a')
        mb << 'b' << 'c'

        received = []
        for receive in mb:
            if receive('a'):
                received.append('a')
            if receive('c'):
                received.append('c')
                break

        # a was taken from save queue, c from mailbox
        print received
        assert received == ['a', 'c']
        # b was not matched and is the new content of the save queue
        assert mb._save_queue.qsize() == 1
        assert mb._save_queue.get_nowait() == 'b'
        assert mb._mailbox.qsize() == 0

    def test_match(self):
        """Test that the ``receive`` object as the proper attributes
        after a successful match.``"""
        mb = Mailbox()
        mb << 'a'
        for receive in mb:
            if receive('a'):
                assert receive.message == 'a'
                assert receive.match == None
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


class TestMatching(object):
    """Test the specific matching.
    """
