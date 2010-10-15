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
import unittest
import time

from keyexchange.filtering import IPFiltering
from keyexchange.util import MemoryClient
from webtest import TestApp
from webob.exc import HTTPForbidden


class FakeApp(object):
    def __call__(self, environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return ['something', 'valid']


class TestIPFiltering(unittest.TestCase):

    def setUp(self):
        app = IPFiltering(FakeApp(), max_calls=5, period=.5)
        self.app = TestApp(app)
        self.mem = isinstance(app.cache.cache, MemoryClient)

    def tearDown(self):
        # flushing 127.0.0.1
        self.app.app.cache.delete('127.0.0.1')
        self.app.app.bcache.delete('127.0.0.1')

    def test_reached_max(self):
        env = {'REMOTE_ADDR': '127.0.0.1'}

        # no ip, no chocolate
        try:
            self.app.get('/', status=403)
        except HTTPForbidden:
            pass

        # doing 5 calls
        for i in range(5):
            self.app.get('/', status=200, extra_environ=env)

        # the next call should be rejected
        try:
            self.app.get('/', status=403, extra_environ=env)
        except HTTPForbidden:
            pass

        if self.mem:
            return

        # TTL test - we make the assumption that the beginning of the
        # test took less than 1.5s

        # we should be on track now
        time.sleep(1.5)
        self.app.get('/', status=200, extra_environ=env)
