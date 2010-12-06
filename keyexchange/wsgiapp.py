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
KeyExchange server - see https://wiki.mozilla.org/Services/Sync/SyncKey/J-PAKE
"""
import datetime
import re
from hashlib import md5
import json
import time
import random

from webob.dec import wsgify
from webob.exc import (HTTPNotModified, HTTPNotFound, HTTPServiceUnavailable,
                       HTTPBadRequest, HTTPMethodNotAllowed,
                       HTTPMovedPermanently)

from services.cef import log_failure
from services.util import convert_config, filter_params

from keyexchange.util import (generate_cid, json_response, CID_CHARS,
                              PrefixedCache, get_memcache_class)
from keyexchange.filtering import IPFiltering


_URL = re.compile('^/(new_channel|report|[%s]+)/?$' % CID_CHARS)
_CPREFIX = 'keyexchange:'
_INC_KEY = '%schannel_id' % _CPREFIX
_DELETE_LOG = 'DeleteLog'
_INVALID_CID = 'InvalidChannelId'
_INVALID_UID = 'InvalidClientId'
_UNKNOWN_UID = 'UnknownClientId'
_BLACKLISTED = 'BlacklistedIP'
_REPORT = 'Report'


def _cid2str(cid):
    if cid is None:
        return 'EMPTY'
    return cid


class KeyExchangeApp(object):

    def __init__(self, config):
        self.config = config
        self.cid_len = config.get('keyexchange.cid_len', 4)
        self.ttl = config.get('keyexchange.ttl', 300)
        self.max_gets = config.get('keyexchange.max_gets', 6)
        self.root = self.config.get('keyexchange.root_redirect')
        servers = config.get('keyexchange.cache_servers', ['127.0.0.1:11211'])
        if isinstance(servers, str):
            self.cache_servers = [servers]
        else:
            self.cache_servers = servers
        use_memory = config.get('keyexchange.use_memory', False)
        cache = get_memcache_class(use_memory)(self.cache_servers)
        self.cache = PrefixedCache(cache, _CPREFIX)

    def _get_new_cid(self, client_id):
        tries = 0
        ttl = time.time() + self.ttl
        content = ttl, [client_id], '{}', None

        while tries < 100:
            new_cid = generate_cid(self.cid_len)
            if self.cache.get(new_cid) is not None:
                tries += 1
                continue   # already taken

            success = self.cache.add(new_cid, content, time=ttl)
            if success:
                break
            tries += 1

        if not success:
            raise HTTPServiceUnavailable()

        return new_cid

    def _health_check(self):
        """Checks that memcache is up and works as expected"""
        rand = ''.join([random.choice('abcdefgh1234567') for i in range(50)])
        key = 'test_%s' % rand
        success = self.cache.add(key, 'test')
        if not success:
            raise HTTPServiceUnavailable()
        stored = self.cache.get(key)
        if stored != 'test':
            raise HTTPServiceUnavailable()
        self.cache.delete(key)
        stored = self.cache.get(key)
        if stored is not None:
            raise HTTPServiceUnavailable()

    @wsgify
    def __call__(self, request):
        request.config = self.config
        client_id = request.headers.get('X-KeyExchange-Id')
        method = request.method
        url = request.path_info

        # the root does a health check on memcached, then
        # redirects to services.mozilla.com
        if url == '/':
            if method != 'GET':
                raise HTTPMethodNotAllowed()
            self._health_check()
            raise HTTPMovedPermanently(location=self.root)

        match = _URL.match(url)
        if match is None:
            raise HTTPNotFound()

        url = match.group(1)
        if url == 'new_channel':
            # creation of a channel
            if method != 'GET':
                raise HTTPMethodNotAllowed()
            if not self._valid_client_id(client_id):
                # The X-KeyExchange-Id is valid
                try:
                    log = 'Invalid X-KeyExchange-Id value: "%s"' % \
                            _cid2str(client_id)
                    log_failure(log, 5, request.environ, self.config,
                                signature=_INVALID_UID)
                finally:
                    raise HTTPBadRequest()

            return json_response(self._get_new_cid(client_id))
        elif url == 'report':
            if method != 'POST':
                raise HTTPMethodNotAllowed()
            return self.report(request, client_id)

        # validating the client id - or registering id #2
        channel_content = self._check_client_id(url, client_id, request)

        # actions are dispatched in this class
        method = getattr(self, '%s_channel' % method.lower(), None)
        if method is None:
            raise HTTPNotFound()

        return method(request, url, channel_content)

    def _valid_client_id(self, client_id):
        return client_id is not None and len(client_id) == 256

    def _check_client_id(self, channel_id, client_id, request):
        """Registers the client id into the channel.

        If there are already two registered ids, the channel is closed
        and we send back a 400. Also returns the new channel content.
        """
        if not self._valid_client_id(client_id):
            # the key is invalid
            try:
                log = 'Invalid X-KeyExchange-Id value: "%s"' % \
                        _cid2str(client_id)
                log_failure(log, 5, request.environ, self.config,
                            signature=_INVALID_UID)
            finally:
                # we need to kill the channel
                if not self._delete_channel(channel_id):
                    log_failure('Could not delete channel "%s"' % channel_id,
                                5, request.environ, self.config,
                                signature=_DELETE_LOG)

                raise HTTPBadRequest()

        content = self.cache.get(channel_id)
        if content is None:
            # we have a valid channel id but it does not exists.
            log = 'Requested an invalid channel id'
            log_failure(log, 5, request.environ, self.config,
                        signature=_INVALID_CID)
            raise HTTPNotFound()

        ttl, ids, data, etag = content
        if len(ids) < 2:
            # first or second id, if not already registered
            if client_id in ids:
                return content   # already registered
            ids.append(client_id)
        else:
            # already full, so either the id is present, either it's a 3rd one
            if client_id in ids:
                return  content  # already registered

            # that's an unknown id, hu-ho
            try:
                log = 'Unknown X-KeyExchange-Id value: "%s"' % client_id
                log_failure(log, 5, request.environ, self.config,
                            signature=_UNKNOWN_UID)
            finally:
                if not self._delete_channel(channel_id):
                    log_failure('Could not delete channel "%s"' % channel_id,
                                5, request.environ, self.config,
                                signature=_DELETE_LOG)

                raise HTTPBadRequest()

        content = ttl, ids, data, etag

        # looking good
        if not self.cache.set(channel_id, content, time=ttl):
            raise HTTPServiceUnavailable()

        return content

    def _etag(self, data, dt=None):
        if dt is None:
            dt = datetime.datetime.now()
        return md5('%s:%s' % (len(data), dt.isoformat())).hexdigest()

    def put_channel(self, request, channel_id, existing_content):
        """Append data into channel."""
        ttl, ids, old_data, old_etag = existing_content
        data = request.body
        etag = self._etag(data)
        if not self.cache.set(channel_id, (ttl, ids, request.body, etag),
                              time=ttl):
            raise HTTPServiceUnavailable()

        return json_response('', etag=etag)

    def get_channel(self, request, channel_id, existing_content):
        """Grabs data from channel if available."""
        ttl, ids, data, etag = existing_content

        # check the If-None-Match header
        if request.if_none_match is not None:
            if (hasattr(request.if_none_match, 'etags') and
                etag in request.if_none_match.etags):
                raise HTTPNotModified()

        # keep the GET counter up-to-date
        # the counter is a separate key
        deletion = False
        ckey = 'GET:%s' % channel_id
        count = self.cache.get(ckey)
        if count is None:
            self.cache.set(ckey, '1')
        else:
            if int(count) + 1 == self.max_gets:
                # we reached the last authorized call, the channel is remove
                # after that
                deletion = True
            else:
                self.cache.incr(ckey)

        try:
            return json_response(data, dump=False, etag=etag)
        finally:
            # deleting the channel in case we did all GETs
            if deletion:
                if not self._delete_channel(channel_id):
                    log_failure('Could not delete channel "%s"' % channel_id,
                                5, request.environ, self.config,
                                signature=_DELETE_LOG)

    def _delete_channel(self, channel_id):
        self.cache.delete('GET:%s' % channel_id)
        res = self.cache.get(channel_id)
        if res is None:
            return True   # already gone
        return self.cache.delete(channel_id)

    def blacklisted(self, ip, environ):
        log_failure('%s blacklisted' % ip, 5, environ, self.config,
                    signature=_BLACKLISTED)

    def report(self, request, client_id):
        """Reports a log and delete the channel if relevant"""
        # logging the report
        log = request.headers.get('X-KeyExchange-Log', '')
        log += '\n%s' % request.body[:2000]
        log_failure(log, 5, request.environ, self.config, signature=_REPORT)

        # removing the channel if present
        channel_id = request.headers.get('X-KeyExchange-Cid')
        if client_id is not None and channel_id is not None:
            content = self.cache.get(channel_id)
            if content is not None:
                # the channel is still existing
                ttl, ids, data, etag = content

                # if the client_ids is in ids, we allow the deletion
                # of the channel
                if not self._delete_channel(channel_id):
                    log_failure('Could not delete channel "%s"' % channel_id,
                                5, request.environ, self.config,
                                signature=_DELETE_LOG)
        return json_response('')


def make_app(global_conf, **app_conf):
    """Returns a Key Exchange Application."""
    global_conf.update(app_conf)
    config = convert_config(global_conf)
    app = KeyExchangeApp(config)
    blacklisted = app.blacklisted

    # hooking a profiler
    if global_conf.get('profile', 'false').lower() == 'true':
        from repoze.profile.profiler import AccumulatingProfileMiddleware
        app = AccumulatingProfileMiddleware(app, log_filename='profile.log',
                                            cachegrind_filename='cachegrind.out',
                                            discard_first_request=True,
                                            flush_at_shutdown=True,
                                            path='/__profile__')

    # hooking a client debugger
    if global_conf.get('client_debug', 'false').lower() == 'true':
        from paste.exceptions.errormiddleware import ErrorMiddleware
        app = ErrorMiddleware(app, debug=True,
                              show_exceptions_in_wsgi_errors=True)

    # hooking a stdout logger
    if global_conf.get('debug', 'false').lower() == 'true':
        from paste.translogger import TransLogger
        app = TransLogger(app, logger_name='jpakeapp',
                          setup_console_handler=True)

    # IP Filtering middleware
    if config.get('filtering.use', False):
        del config['filtering.use']
        app = IPFiltering(app, callback=blacklisted,
                          **filter_params('filtering', config))

    return app
