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
IP Filtering middleware.
"""
import time
from webob.exc import HTTPForbidden, HTTPBadRequest
from keyexchange.util import Cache, PrefixedCache

_CPREFIX = 'keyexchange-ips:'
_CBADREQ_PREFIX = 'keyexchange-br-ips:'

class IPFiltering(object):
    """This middleware will:

    - reject all new attempts made by an IP, if this IP already made too
      many attempts during a certain period.

    - log ips that have issues 400s on the application.
    """
    def __init__(self, app, cache_servers=None, period=300, max_calls=100,
                 max_bad_request_calls=5, bad_request_period=86400):
        self.app = app
        if cache_servers is None:
            cache_servers = ['127.0.0.1:11211']
        self.cache = PrefixedCache(Cache(cache_servers), _CPREFIX)
        self.max_calls = max_calls
        self.period = period
        self.max_bad_request_calls = max_bad_request_calls
        self.bad_request_period = bad_request_period
        self.bcache = PrefixedCache(Cache(cache_servers), _CBADREQ_PREFIX)

    def _inc_cache(self, cache, ip, period, count_checker=None):
        content = cache.get(ip)
        if content is None:
            ttl = time.time() + period
            cache.set(ip, (ttl, 1), time=ttl)
            return
        ttl, count = content
        if count_checker is not None:
            count_checker(count)
        cache.set(ip, (ttl, count + 1), time=ttl)

    def _check_counter(self, ip):
        def _check_count(count):
            if count >= self.max_calls:
                # we just reached the treshold
                raise HTTPForbidden()
        self._inc_cache(self.cache, ip, self.period, _check_count)

    def _check_bad_reqs(self, ip):
        content = self.bcache.get(ip)
        if content is None:
            return
        ttl, count = content
        if count >= self.max_bad_request_calls:
            # we just reached the treshold
            raise HTTPForbidden()

    def __call__(self, environ, start_response):
        # what's the remote ip ?
        ip = environ.get('REMOTE_ADDR')
        if ip is None:
            # not acceptable
            raise HTTPForbidden()

        # checking for the bad requests this IP have done so far
        self._check_bad_reqs(ip)

        # checking for the number of attempts for this IP
        self._check_counter(ip)

        try:
            return self.app(environ, start_response)
        except HTTPBadRequest:
            # this IP issued a 400. We want to log that
            self._inc_cache(self.bcache, ip, self.bad_request_period)
            raise
