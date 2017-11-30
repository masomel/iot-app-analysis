"""Parse mystery style generated by MTA at caiwireless.net."""

import re

from email.iterators import body_line_iterator
from enum import Enum
from flufl.bounce.interfaces import (
    IBounceDetector, NoFailures, NoTemporaryFailures)
from public import public
from zope.interface import implementer


tcre = re.compile(
    r'the following recipients did not receive this message:',
    re.IGNORECASE)
acre = re.compile(
    r'<(?P<addr>[^>]*)>')


class ParseState(Enum):
    start = 0
    tag_seen = 1


@public
@implementer(IBounceDetector)
class Caiwireless:
    """Parse mystery style generated by MTA at caiwireless.net."""

    def process(self, msg):
        if msg.get_content_type() == 'multipart/mixed':
            state = ParseState.start
            # This format thinks it's a MIME, but it really isn't.
            for line in body_line_iterator(msg):
                line = line.strip()
                if state is ParseState.start and tcre.match(line):
                    state = ParseState.tag_seen
                elif state is ParseState.tag_seen and line:
                    mo = acre.match(line)
                    if mo:
                        return NoTemporaryFailures, set(mo.group('addr'))
                    else:
                        break
        return NoFailures