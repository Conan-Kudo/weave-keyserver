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
calls. If an IP as a high number of calls, it's blacklisted.

For the bad request counter, the same technique is used.

Blacklisted IPs are kept in memory with a TTL.
"""
import time
import threading


class _Syncer(threading.Thread):

    def __init__(self, blacklist, frequency=5):
        threading.Thread.__init__(self)
        self.blacklist = blacklist
        self.frequency = frequency
        self.running = False

    def run(self):
        self.running = True
        while self.running:
            # this syncs the blacklist
            self.blacklist.save()
            time.sleep(self.frequency)

    def join(self):
        if not self.running:
            return
        self.running = False
        threading.Thread.join(self)


class Blacklist(object):
    """IP Blacklist with TTL and memcache support.

    IPs are saved/loaded from Memcached so several apps can share the
    blacklist.
    """
    def __init__(self, cache_server=None, frequency=5):
        self._ttls = {}
        self._cache_server = cache_server
        self.ips = set()
        self._dirty = False
        self._lock = threading.RLock()
        self._syncer = _Syncer(self, frequency=frequency)
        # sys.exit() call all threads join() in >= 2.6.5
        self._syncer.start()

    def update(self):
        """Loads the IP list from memcached."""
        if self._cache_server is None:
            return
        self._lock.acquire()
        try:
            data = self._cache_server.get('keyexchange:blacklist')
            # merging the memcached values
            if data is not None:
                ips, ttls = data
                # get new blacklisted IP
                if not self.ips.issuperset(ips):
                    self.ips.union(ips)
                    self._ttls.update(ttls)
        finally:
            self._lock.release()

    def save(self):
        """Save the IP into memcached if needed."""
        if self._cache_server is None or not self._dirty:
            return

        self._lock.acquire()
        try:
            # doing a CAS to avoid race conditions
            tries = 0
            while tries < 10:
                data = self.ips, self._ttls
                if self._cache_server.cas('keyexchange:blacklist', data):
                    self._dirty = False
                    break
                self.update()  # reload
                tries += 1
        finally:
            self._lock.release()

    def add(self, elmt, ttl=None):
        self._lock.acquire()
        try:
            self.ips.add(elmt)
            if ttl is not None:
                self._ttls[elmt] = time.time() + ttl
            else:
                self._ttls[elmt] = None
            self._dirty = True
        finally:
            self._lock.release()

    def remove(self, elmt):
        self._lock.acquire()
        try:
            self.ips.remove(elmt)
            del self._ttls[elmt]
            self._dirty = True
        finally:
            self._lock.release()

    def __contains__(self, elmt):
        self._lock.acquire()
        try:
            found = elmt in self.ips
            if found:
                ttl = self._ttls[elmt]
                if ttl is None:
                    return True
                if self._ttls[elmt] - time.time() <= 0:
                    # this will not provocate a deadlock
                    # since we use a Re-entrant lock.
                    self.remove(elmt)
                    return False
            return found
        finally:
            self._lock.release()

    def __len__(self):
        return len(self.ips)