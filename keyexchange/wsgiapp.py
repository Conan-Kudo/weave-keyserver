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
J-PAKE server - see https://wiki.mozilla.org/Services/Sync/SyncKey/J-PAKE
"""
import datetime
import re
from hashlib import md5
import json
import time

from paste.translogger import TransLogger
from repoze.profile.profiler import AccumulatingProfileMiddleware as Profiler

from webob.dec import wsgify
from webob.exc import (HTTPNotModified, HTTPNotFound, HTTPServiceUnavailable,
                       HTTPBadRequest)

try:
    from pylibmc import Client
except (ImportError, RuntimeError):
    try:
        from memcache import Client  # NOQA
    except ImportError:
        from keyexchange.util import MemoryClient as Client  # NOQA

from keyexchange.util import (generate_cid, json_response, CID_CHARS,
                              PrefixedCache)


_URL = re.compile('/(new_channel|[a-zA-Z0-9]*)/?')
_CPREFIX = 'keyexchange:'
_INC_KEY = '%schannel_id' % _CPREFIX
_NOT_FOUND, _FAILED, _SUCCESS = range(3)


class KeyExchangeApp(object):

    def __init__(self, cid_len, cache_servers=None, ttl=300):
        self.cid_len = cid_len
        self.max_combos = len(CID_CHARS) ** cid_len
        self.ttl = ttl
        if cache_servers is None:
            cache_servers = ['127.0.0.1:11211']
        self.cache = PrefixedCache(Client(cache_servers), _CPREFIX)

    def _get_new_cid(self, client_id):
        tries = 0
        ttl = time.time() + self.ttl
        content = ttl, [client_id], json.dumps({}), None

        while tries < 100:
            new_cid = generate_cid(self.cid_len)
            success = self.cache.add(new_cid, content, time=ttl)
            if success:
                break
            tries += 1

        if not success:
            raise HTTPServiceUnavailable()

        return new_cid

    @wsgify
    def __call__(self, request):
        client_id = request.headers.get('X-Weave-ClientID')
        method = request.method
        url = request.environ['PATH_INFO']
        match = _URL.match(url)
        if match is None:
            raise HTTPNotFound()

        url = match.groups()[0]
        if url == 'new_channel':
            # creation of a channel
            if method != 'GET':
                raise HTTPNotFound()
            if not self._valid_client_id(client_id):
                raise HTTPBadRequest()

            return json_response(self._get_new_cid(client_id))

        # validating the client id - or registering id #2
        self._check_client_id(url, client_id)

        # actions are dispatched in this class
        method = getattr(self, '%s_channel' % method.lower(), None)
        if method is None:
            raise HTTPNotFound()

        return method(request, url)

    def _valid_client_id(self, client_id):
        return client_id is not None and len(client_id) == 256

    def _check_client_id(self, channel_id, client_id):
        """Registers the client id into the channel.

        If there are already two registered ids, the channel is closed
        and we send back a 400.
        """
        if not self._valid_client_id(client_id):
            # we need to kill the channel
            self._delete_channel(channel_id)
            raise HTTPBadRequest()

        content = self.cache.get(channel_id)
        if content is None:
            raise HTTPNotFound()

        ttl, ids, data, etag = content
        if len(ids) < 2:
            # first or second id, if not already registered
            if client_id in ids:
                return   # already registered
            ids.append(client_id)
        else:
            # already full, so either the id is present, either it's a 3rd one
            if client_id in ids:
                return  # already registered

            # that's an unknown id
            self._delete_channel(channel_id)
            raise HTTPBadRequest()

        # looking good
        self.cache.set(channel_id, (ttl, ids, data, etag), time=ttl)

    def _etag(self, data, dt=None):
        if dt is None:
            dt = datetime.datetime.now()
        return md5('%s:%s' % (len(data), dt.isoformat())).hexdigest()

    def put_channel(self, request, channel_id):
        """Append data into channel."""
        content = self.cache.get(channel_id)
        if content is None:
            raise HTTPNotFound()

        ttl, ids, old_data, old_etag = content
        data = request.body
        etag = self._etag(data)
        if not self.cache.set(channel_id, (ttl, ids, request.body, etag),
                              time=ttl):
            raise HTTPServiceUnavailable()

        return json_response('', etag=etag)

    def get_channel(self, request, channel_id):
        """Grabs data from channel if available."""
        content = self.cache.get(channel_id)
        if content is None:
            raise HTTPNotFound()

        ttl, ids, data, etag = content

        # check the If-None-Match header
        if request.if_none_match is not None:
            if (hasattr(request.if_none_match, 'etags') and
                etag in request.if_none_match.etags):
                raise HTTPNotModified()

        return json_response(data, dump=False, etag=etag)

    def _delete_channel(self, channel_id):
        res = self.cache.get(channel_id)
        if res is None:
            return _NOT_FOUND
        res = self.cache.delete(channel_id)
        if not res:
            # failed to delete
            return _FAILED
        return _SUCCESS

    def delete_channel(self, request, channel_id):
        """Delete a channel."""
        res = self._delete_channel(channel_id)
        if res == _NOT_FOUND:
            raise HTTPNotFound()
        elif res == _FAILED:
            raise HTTPServiceUnavailable()
        return json_response('')


def make_app(global_conf, **app_conf):
    """Returns a J-PAKE Application."""
    # XXX Probably want to use the new .ini format instead
    cid_len = int(app_conf.get('cid_len', '3'))
    cache = app_conf.get('cache_servers', '127.0.0.1:11211')
    app = KeyExchangeApp(cid_len, cache.split(','))

    # hooking a profiler
    if global_conf.get('profile', 'false').lower() == 'true':
        app = Profiler(app, log_filename='profile.log',
                       cachegrind_filename='cachegrind.out',
                       discard_first_request=True,
                       flush_at_shutdown=True,
                       path='/__profile__')

    # hooking a logger
    if global_conf.get('translogger', 'false').lower() == 'true':
        app = TransLogger(app, logger_name='jpakeapp',
                          setup_console_handler=True)

    return app
