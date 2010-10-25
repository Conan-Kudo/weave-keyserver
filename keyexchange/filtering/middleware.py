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
from collections import deque as _deque

from mako.template import Template

from keyexchange.util import get_memcache_class
from keyexchange.filtering.blacklist import Blacklist

# Make sure we get the IP from any proxy or loadbalancer, if any is used
_IP_HEADERS = ('X-Forwarded-For', 'X_FORWARDED_FOR', 'REMOTE_ADDR')


class deque(_deque):
    def count(self, element):
        """Python implementation of deque.count() for 2.6.
        XXX The 2.7 code is in C but we don't expect this container to have
        more that 2k elements.
        """
        count = 0
        # we need to freeze the sequence while counting, since other threads
        # might add or remove elements.
        for _element in list(self):
            if _element == element:
                count += 1
        return count


class IPFiltering(object):
    """Filtering IPs
    """
    def __init__(self, app, blacklist_ttl=300, br_blacklist_ttl=86400,
                 queue_size=1000, br_queue_size=200, treshold=.5,
                 br_treshold=.5, cache_servers=['127.0.0.0.1:11211'],
                 admin_page=None, use_memory=False, refresh_frequency=1):

        """Initializes the middleware.

        - app: the wsgi application the middleware wraps
        - blacklist_ttl: defines how long in seconds an IP is blacklisted
        - br_blacklist_ttl: defines how long in seconds an IP that did too many
          bad requests is blacklisted
        - queue_size: Size of the queue used to keep track of the last callers
        - br_queue_size: Size of the queue used to keep track of the last
          callers that provokated a bad request.
        - treshold: ratio to mark an IP as an attacker. The ratio is the number
          of calls the IP made
        - br_treshold: ratio to mark an IP as an attacker. The ratio is the
          number of bad requests calls the IP made
        """
        self.app = app
        self.blacklist_ttl = blacklist_ttl
        self.br_blacklist_ttl = br_blacklist_ttl
        self.queue_size = queue_size
        self.br_queue_size = br_queue_size
        self.treshold = float(treshold)
        self.br_treshold = float(br_treshold)
        self._last_ips = deque(maxlen=queue_size)
        self._last_br_ips = deque(maxlen=br_queue_size)
        if isinstance(cache_servers, str):
            cache_servers = [cache_servers]
        self._cache_server = get_memcache_class(use_memory)(cache_servers)
        self._blacklisted = Blacklist(self._cache_server, refresh_frequency)
        if admin_page is not None and not admin_page.startswith('/'):
            admin_page = '/' + admin_page
        self.admin_page = admin_page
        admin_mako = os.path.join(os.path.dirname(__file__), 'admin.mako')
        self._admin_tpl = Template(filename=admin_mako)

    def _check_ip(self, ip):
        # insert the IP in the queue
        # if the queue is full, the opposite-end item is discarded
        self._last_ips.appendleft(ip)

        # counts its ratio in the queue
        count = self._last_ips.count(ip)
        if (count > 0 and
            float(count) / float(self.queue_size) >= self.treshold):
            # blacklisting the IP
            self._blacklisted.add(ip, self.blacklist_ttl)

    def _inc_bad_request(self, ip):
        # insert the IP in the br queue
        # if the queue is full, the opposite-end item is discarded
        self._last_br_ips.appendleft(ip)

        # counts its occurences in the queue
        count = self._last_br_ips.count(ip)
        if count > 0 and float(count) / self.br_queue_size >= self.br_treshold:
            # blacklisting the IP
            self._blacklisted.add(ip, self.br_blacklist_ttl)

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
                                       admin_page=self.admin_page)]

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

        if ip is None or ip in self._blacklisted:
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
