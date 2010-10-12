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
Load test for the J-Pake server
"""
import random
import json
import unittest
import string
import time
import threading

from keyexchange.tests import _patch
from keyexchange.tests.client import JPAKE

from funkload.FunkLoadTestCase import FunkLoadTestCase
from funkload.utils import Data


class User(threading.Thread):

    def __init__(self, app,  name, passwd, data=None, cid=None, root=''):
        threading.Thread.__init__(self)
        self.name = name
        self.pake = JPAKE(passwd, signerid=name)
        self.data = data
        self.root = root
        self.app = app
        if data is not None:
            res = self.app.get(self.root+'/new_channel')
            self.cid = str(json.loads(res.body))
        else:
            self.cid = cid
        self.curl = self.root + '/%s' % self.cid

    def runTest(self):
        pass

    def _wait_data(self, etag=''):
        time.sleep(.2)
        status = 304
        attempts = 0
        while status == 304 and attempts < 15:
            try:
                res = self.app.get(self.curl, headers={'If-None-Match': etag})
            except AssertionError, e:
                if not '304' in str(e):
                    raise
                else:
                    status = 304
            else:
                status = res.code
            attempts +=1
            if status == 304:
                time.sleep(.1)

        if status == 304 and attempts >= 15:
            raise AssertionError('Failed to get next step')

        body = json.loads(res.body)
        def _clean(body):
            if isinstance(body, unicode):
                return str(body)
            res = {}
            for key, value in body.items():
                if isinstance(value, unicode):
                    value = str(value)
                elif isinstance(value, dict):
                    value = _clean(value)
                res[str(key)] = value
            return res
        return _clean(body)


class Sender(User):
    def run(self):
        # step 1
        one = json.dumps(self.pake.one(), ensure_ascii=True)
        res = self.app.put(self.curl, Data('application/json', one))
        etag = res.headers['ETag']

        other_one = self._wait_data(etag)

        # step 2
        two = json.dumps(self.pake.two(other_one))
        res = self.app.put(self.curl, Data('application/json', two))
        etag = res.headers['ETag']

        # now wait for step 2 from the other iside
        other_two = self._wait_data(etag)

        # then we build the key
        self.key = self.pake.three(other_two)

        # and we send the data (no crypting in the tests)
        data = json.dumps(self.data)
        res = self.app.put(self.curl, Data('application/json', data))


class Receiver(User):
    def run(self):
        # waiting for step 1
        other_one = self._wait_data()

        # step 1
        one = json.dumps(self.pake.one(), ensure_ascii=True)
        res = self.app.put(self.curl, Data('application/json', one))
        etag = res.headers['ETag']

        # waiting for step 2
        other_two = self._wait_data(etag)

        # sending step 2
        two = json.dumps(self.pake.two(other_one))
        res = self.app.put(self.curl, Data('application/json', two))
        etag = res.headers['ETag']

        # then we build the key
        self.key = self.pake.three(other_two)

        # and we get the data (no crypting in the tests)
        self.data = self._wait_data(etag)


class StressTest(FunkLoadTestCase):

    def setUp(self):
        self.root = self.conf_get('main', 'url')
        self._lock = threading.RLock()

    def acquire(self):
        self._lock.acquire()

    def release(self):
        self._lock.release()

    def put(self, *args, **kw):
        self.acquire()
        try:
            return FunkLoadTestCase.put(self, *args, **kw)
        finally:
            self.release()

    def get(self, *args, **kw):
        self.acquire()
        if 'headers' in kw:
            headers = kw['headers']
            for key, value in headers.items():
                self.setHeader(key, value)
            del kw['headers']
        else:
            headers = []
        try:
            return FunkLoadTestCase.get(self, *args, **kw)
        finally:
            for key in headers:
                self.delHeader(key)
            self.release()

    def _random_name(self):
        name = ''.join([random.choice(string.ascii_letters)
                        for i in range(4)])
        return name + str(round(time.time()))

    def test_session(self):
        # we want to send data in a secure channel
        data = {'username': 'sender',
                'password': 'secret'}

        # let's create two end-points
        sender = Sender(self, self._random_name(), 'secret', data,
                        root=self.root)

        # sender creates a cid, receiver has to provide
        receiver = Receiver(self, self._random_name(), 'secret',
                            cid=sender.cid, root=self.root)

        # sender starts
        sender.start()

        # let's wait a bit
        time.sleep(.2)

        # receiver starts next
        receiver.start()

        # let's wait for the transaction to end
        sender.join()
        receiver.join()

        # sender and receiver should have the same key
        self.assertEqual(sender.key, receiver.key)

        # receiver should have received the "encrypted" data from sender
        original_data = sender.data.items()
        original_data.sort()
        received_data = receiver.data.items()
        received_data.sort()
        self.assertEqual(original_data, received_data)

if __name__ == '__main__':
    unittest.main()
