# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Sync Server
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2010
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Tarek Ziade (tarek@mozilla.com)
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****
"""
IP Filtering middleware. This middleware will:

- Reject all new attempts made by an IP, if this IP already made too many
  attempts.
- Reject IPs are are making too many bad requests

To perform this, we keep a LRU of the last N ips in memory and increment the
calls. If an IP as a high number of calls, it's blaclisted.

For the bad request counter, the same technique is used.

Blacklisted IPs are kept in memcached with a TTL.
"""
import time
from collections import deque as _deque

from webob.exc import HTTPForbidden, HTTPBadRequest


class deque(_deque):
    def count(self, element):
        """Python implementation of deque.count() for 2.6.
        XXX Need to backport the existing 2.7 code to avoid O(n) here
        """
        count = 0
        for _element in self:
            if _element == element:
                count += 1
        return count


class Blacklist(set):
    """Set with TTL.

    XXX need to check for TTL in more API than __contains__
    """
    def __init__(self):
        self._ttls = {}

    def add(self, elmt, ttl=None):
        set.add(self, elmt)
        self._ttls[elmt] = time.time() + ttl

    def remove(self, elmt):
        set.remove(self, elmt)
        del self._ttls[elmt]

    def __contains__(self, elmt):
        found = set.__contains__(self, elmt)
        if found:
            ttl = self._ttls[elmt]
            if ttl is None:
                return True
            if self._ttls[elmt] - time.time() <= 0:
                self.remove(elmt)
                return False
        return found


class IPFiltering(object):
    """Filtering IPs
    """
    def __init__(self, app, blacklist_ttl=300, br_blacklist_ttl=86400,
                 queue_size=1000, br_queue_size=200, treshold=.5,
                 br_treshold=.5):

        """Initializes the middleware.

        - app: the wsgi application the middleware provides
        - blacklist_ttl: defines how long in seconds an IP is blacklisted
        - br_blacklist_ttl: defines how long in seconds an IP that did too many
          bad requests is blacklisted
        - queue_size: Size of the queue used to keep track of the last callers
        - br_queue_size: Size of the queue used to keep track of the last callers
          that provokated a bad request.
        - treshold: ratio to mark an IP as an attacker. The ratio is the number
          of calls the IP made
        - br_treshold: ratio to mark an IP as an attacker. The ratio is the number
          of bad requests calls the IP made
        """
        self.app = app
        self.blacklist_ttl = blacklist_ttl
        self.br_blacklist_ttl = br_blacklist_ttl
        self.queue_size = queue_size
        self.br_queue_size = br_queue_size
        self.treshold = float(treshold)
        self.br_treshold = float(br_treshold)
        self._last_ips = deque()
        self._last_br_ips = deque()
        # XXX see if we want to keep this in memory or share it in memcached
        self._blacklisted = Blacklist()

    def _check_ip(self, ip):
        # is this IP already blacklisted ?
        if ip in self._blacklisted:
            # no, it is blacklisted !
            raise HTTPForbidden()

        # insert the IP in the queue
        self._last_ips.appendleft(ip)

        # counts its ratio in the queue
        count = self._last_ips.count(ip)
        if (count > 0 and
            float(count) / float(self.queue_size) >= self.treshold):
            # blacklisting the IP
            self._blacklisted.add(ip, self.blacklist_ttl)

        # popping the oldest IP if the queue is full
        if len(self._last_ips) >= self.queue_size:
            self._last_ips.pop()

    def _inc_bad_request(self, ip):
        # insert the IP in the br queue
        self._last_br_ips.insert(0, ip)

        # counts its occurences in the queue
        count = self._last_br_ips.count(ip)
        if count > 0 and float(count) / self.br_queue_size >= self.br_treshold:
            # blacklisting the IP
            self._blacklisted.add(ip, self.br_blacklist_ttl)

        # poping the oldest IP if the queue is full
        if len(self._last_br__ips) >= self.br_queue_size:
            self._last_br_ips.pop()

    def __call__(self, environ, start_response):
        # what's the remote ip ?
        ip = environ.get('REMOTE_ADDR')
        if ip is None:
            # not acceptable
            raise HTTPForbidden()

        # checking for the IP in our counter
        self._check_ip(ip)
        try:
            return self.app(environ, start_response)
        except HTTPBadRequest:
            # this IP issued a 400. We want to log that
            self._inc_bad_request(ip)
            raise
