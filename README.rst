gevent-erlang-mode
==================

Contains ad hoc, informally-specified, bug-ridden, slow implementations of
some Erlang-style concepts, ported to gevent_.

.. _gevent: http://www.gevent.org/


The Mailbox
-----------

    from erlangmode import Mailbox

    process = Mailbox()
    process << 'reload', {'timeout': 5}

    for receive in process:
        if receive(str, dict):
            command, options = receive.match
            run_command(command, options)
            break

See module documentation for more.


Utilities
---------

    from erlangmode import send_after
    timer = send_after(10, mailbox, 'message')
    timer.reset()
    timer.cancel()

