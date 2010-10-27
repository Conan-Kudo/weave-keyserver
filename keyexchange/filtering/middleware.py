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
import os
import cgi
from collections import deque

from mako.template import Template

from keyexchange.util import get_memcache_class
from keyexchange.filtering.blacklist import Blacklist

# Make sure we get the IP from any proxy or loadbalancer, if any is used
_IP_HEADERS = ('X-Forwarded-For', 'X_FORWARDED_FOR', 'REMOTE_ADDR')


class IPQueue(deque):
    """IP Queue that keeps a counter for each IP.

    When an IP comes in, it's append in the left and the counter
    initialized to 1.

    If the IP is already in the queue, its counter is incremented,
    and it's moved back to the left.

    When the queue is full, the right element is discarded.
    """
    def __init__(self, maxlen=200):
        self._ips = deque()
        self._counter = dict()
        self._maxlen = maxlen

    def append(self, ip):
        """Adds the IP and raise the counter accordingly."""
        if ip not in self._ips:
            self._ips.appendleft(ip)
            self._counter[ip] = 1
        else:
            self._ips.remove(ip)
            self._ips.appendleft(ip)
            self._counter[ip] += 1

        if len(self._ips) > self._maxlen:
            ip = self._ips.pop()
            del self._counter[ip]

    def count(self, ip):
        """Returns the IP count."""
        return self._counter.get(ip, 0)

    def __len__(self):
        return len(self._ips)


class IPFiltering(object):
    """Filtering IPs
    """
    def __init__(self, app, blacklist_ttl=300, br_blacklist_ttl=86400,
                 queue_size=200, br_queue_size=20, treshold=20,
                 br_treshold=5, cache_servers=['127.0.0.0.1:11211'],
                 admin_page=None, use_memory=False, refresh_frequency=1,
                 observe=False, callback=None):

        """Initializes the middleware.

        - app: the wsgi application the middleware wraps
        - blacklist_ttl: defines how long in seconds an IP is blacklisted
        - br_blacklist_ttl: defines how long in seconds an IP that did too many
          bad requests is blacklisted
        - queue_size: Size of the queue used to keep track of the last callers
        - br_queue_size: Size of the queue used to keep track of the last
          callers that provokated a bad request.
        - treshold: max number of calls per IP before we blacklist it.
        - br_treshold: max number of bad request per IP before we blacklist it.
        - observe: if set to True, IPs are still blacklisted but not rejected.
          This mode is useful to observe the behavior of an application without
          rejecting any call, to make sure a configuration works fine. Notice
          that a blacklisted IP will continue to raise its counter in the
          queue.
        - callback: callable that will be called with an IP that is added
          in the blacklist.
        """
        self.app = app
        self.blacklist_ttl = blacklist_ttl
        self.br_blacklist_ttl = br_blacklist_ttl
        self.queue_size = queue_size
        self.br_queue_size = br_queue_size
        self.treshold = treshold
        self.br_treshold = br_treshold
        self.observe = observe
        self._last_ips = IPQueue(queue_size)
        self._last_br_ips = IPQueue(br_queue_size)
        if isinstance(cache_servers, str):
            cache_servers = [cache_servers]
        self._cache_server = get_memcache_class(use_memory)(cache_servers)
        self._blacklisted = Blacklist(self._cache_server, refresh_frequency)
        if admin_page is not None and not admin_page.startswith('/'):
            admin_page = '/' + admin_page
        self.admin_page = admin_page
        admin_mako = os.path.join(os.path.dirname(__file__), 'admin.mako')
        self._admin_tpl = Template(filename=admin_mako)
        self.callback = callback

    def _check_ip(self, ip):
        # insert the IP in the queue
        # if the queue is full, the opposite-end item is discarded
        self._last_ips.append(ip)

        # counts its ratio in the queue
        if self._last_ips.count(ip) >= self.treshold:
            # blacklisting the IP
            self._blacklisted.add(ip, self.blacklist_ttl)
            if self.callback is not None:
                self.callback(ip)

    def _inc_bad_request(self, ip):
        # insert the IP in the br queue
        # if the queue is full, the opposite-end item is discarded
        self._last_br_ips.append(ip)

        # counts its occurences in the queue
        if self._last_br_ips.count(ip) >= self.br_treshold:
            # blacklisting the IP
            self._blacklisted.add(ip, self.br_blacklist_ttl)
            if self.callback is not None:
                self.callback(ip)

    def admin(self, environ, start_response):
        """Displays an admin page containing the blacklisted IPs

        This page is not activated by default.
        """
        post_env = environ.copy()
        post_env['QUERY_STRING'] = ''
        post = cgi.FieldStorage(fp=environ['wsgi.input'], environ=post_env,
                                keep_blank_values=True)
        ips = [ip for ip in post.keys() if post[ip].value == 'on']
        for ip in ips:
            try:
                self._blacklisted.remove(ip)
            except KeyError:
                pass

        headers = [('Content-Type', 'text/html')]
        start_response('200 OK', headers)
        # we want to display the list of blacklisted IPs
        return [self._admin_tpl.render(ips=self._blacklisted.ips,
                                       admin_page=self.admin_page,
                                       observe=self.observe)]

    def __call__(self, environ, start_response):
        # is it an admin call ?
        url = environ.get('PATH_INFO')
        if url is not None and url == self.admin_page:
            return self.admin(environ, start_response)

        start_response_status = []

        def _start_response(status, headers, exc_info=None):
            start_response_status.append(status)
            return start_response(status, headers, exc_info)

        # what's the remote ip ?
        for header in _IP_HEADERS:
            ip = environ.get(header)
            if ip is not None:
                break

        if ip is None or (ip in self._blacklisted and not self.observe):
            # returning a 403
            headers = [('Content-Type', 'text/plain')]
            start_response('403 Forbidden', headers)
            return ["Forbidden: You don't have permission to access"]

        # checking for the IP in our counter
        self._check_ip(ip)

        res = self.app(environ, _start_response)

        if start_response_status[0].startswith('400'):
            # this IP issued a 400. We want to log that
            self._inc_bad_request(ip)

        return res
