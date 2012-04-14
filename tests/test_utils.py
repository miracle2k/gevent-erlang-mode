from erlangmode import send_after, Mailbox
from base import *


class TestSendAfter(object):

    def test_send(self):
        mb = Mailbox()
        send_after(STEP*1.5, mb, 42)
        step(); assert mb._mailbox.qsize() == 0
        step(); assert mb._mailbox.qsize() == 1

    def test_cancel(self):
        mb = Mailbox()
        t = send_after(STEP*1.5, mb, 42)
        step(); t.cancel()
        step(); assert mb._mailbox.qsize() == 0

    def test_cancel_late(self):
        mb = Mailbox()
        t = send_after(STEP*1.5, mb, 42)
        step()
        step(); t.cancel()
        assert mb._mailbox.qsize() == 1

    def test_reset(self):
        mb = Mailbox()
        t = send_after(STEP*1.5, mb, 42)
        step(); t.reset()
        step(); assert mb._mailbox.qsize() == 0
        step(); assert mb._mailbox.qsize() == 1

    def test_none_value(self):
        """If timeout is None, the timer is a noop."""
        mb = Mailbox()
        t = send_after(None, mb, 42)
        step(); assert mb._mailbox.qsize() == 0
        t.reset()
        t.cancel()
        step(); assert mb._mailbox.qsize() == 0

