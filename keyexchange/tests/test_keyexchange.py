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
""" Functional test to simulate a JPake transaction.
"""
import unittest
import threading
import json
import time
import random
import hashlib

from webtest import TestApp

from keyexchange.tests.client import JPAKE
from keyexchange.wsgiapp import make_app
from keyexchange.util import MemoryClient


class User(threading.Thread):

    def __init__(self, name, passwd, app, data=None, cid=None):
        threading.Thread.__init__(self)
        self.app = app
        if hasattr(app, 'root'):
            self.root = app.root
        else:
            self.root = ''
        self.name = name
        self.pake = JPAKE(passwd, signerid=name)
        self.data = data
        hash = hashlib.sha256(str(random.randint(1, 1000))).hexdigest()

        self.id = hash * 4
        if data is not None:
            res = self.app.get(self.root+'/new_channel',
                               headers={'X-KeyExchange-Id': self.id},
                               extra_environ=self.app.env)
            self.cid = str(json.loads(res.body))
        else:
            self.cid = cid
        self.curl = self.root + '/%s' % self.cid

    def _wait_data(self, etag=''):
        status = 304
        attempts = 0
        while status == 304 and attempts < 10:

            res = self.app.get(self.curl,
                               extra_environ=self.app.env,
                               headers={'If-None-Match': etag,
                                        'X-KeyExchange-Id': self.id})

            status = res.status_int
            attempts +=1
            if status == 304:
                time.sleep(.2)

        if status == 304:
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
        headers = {'X-KeyExchange-Id': self.id}
        # step 1
        #print '%s sends step one' % self.name
        one = json.dumps(self.pake.one(), ensure_ascii=True)
        res = self.app.put(self.curl, params=one, headers=headers,
                           extra_environ=self.app.env)
        etag = res.headers['ETag']

        #print '%s now waits for step one from receiver' % self.name
        other_one = self._wait_data(etag)
        #print '%s received step one' % self.name

        # step 2
        #print '%s sends step two' % self.name
        two = json.dumps(self.pake.two(other_one))
        res = self.app.put(self.curl, params=two, headers=headers,
                           extra_environ=self.app.env)
        etag = res.headers['ETag']
        time.sleep(.2)

        # now wait for step 2 from the other iside
        other_two = self._wait_data(etag)
        #print '%s received step two from receiver' % self.name

        # then we build the key
        self.key = self.pake.three(other_two)

        # and we send the data (no crypting in the tests)
        #print '%s sends the data' % self.name
        data = json.dumps(self.data)
        res = self.app.put(self.curl, params=data, headers=headers,
                           extra_environ=self.app.env)


class Receiver(User):
    def run(self):
        headers = {'X-KeyExchange-Id': self.id}

        # waiting for step 1
        #print '%s waits for step one from sender' % self.name
        other_one = self._wait_data()

        # step 1
        #print '%s sends step one to receiver' % self.name
        one = json.dumps(self.pake.one(), ensure_ascii=True)
        res = self.app.put(self.curl, params=one, headers=headers,
                           extra_environ=self.app.env)
        etag = res.headers['ETag']

        # waiting for step 2
        #print '%s waits for step two from sender' % self.name
        other_two = self._wait_data(etag)

        # sending step 2
        #print '%s sends step two' % self.name
        two = json.dumps(self.pake.two(other_one))
        res = self.app.put(self.curl, params=two, headers=headers,
                           extra_environ=self.app.env)
        etag = res.headers['ETag']

        # then we build the key
        self.key = self.pake.three(other_two)

        # and we get the data (no crypting in the tests)
        self.data = self._wait_data(etag)
        #print '%s received the data' % self.name


class TestWsgiApp(unittest.TestCase):

    def setUp(self):
        app = make_app({})
        app.config = {}
        # we don't test this here
        app.max_bad_request_calls = 1000
        self.app = TestApp(app)
        self.app.env = self.env = {'REMOTE_ADDR': '127.0.0.1'}

    def test_session(self):
        # we want to send data in a secure channel
        data = {'username': 'bob',
                'password': 'secret'}

        # let's create two end-points
        bob = Sender('Bob', 'secret', self.app, data)

        # bob creates a cid, sarah has to provide
        sarah = Receiver('Sarah', 'secret', self.app, cid=bob.cid)

        # bob starts
        bob.start()

        # let's wait a bit
        time.sleep(.5)

        # sarah starts next
        sarah.start()

        # let's wait for the transaction to end
        bob.join()
        sarah.join()

        # bob and sarah should have the same key
        self.assertEqual(bob.key, sarah.key)

        # sarah should have received the "encrypted" data from bob
        original_data = bob.data.items()
        original_data.sort()
        received_data = sarah.data.items()
        received_data.sort()
        self.assertEqual(original_data, received_data)

    def test_behavior(self):
        headers = {'X-KeyExchange-Id': 'b' * 256}

        # make sure we can't play with a channel that does not exist
        self.app.put('/boo', params='somedata', headers=headers, status=404,
                     extra_environ=self.env)
        self.app.get('/boo', status=404, headers=headers,
                     extra_environ=self.env)
        self.app.delete('/boo', status=404, headers=headers,
                        extra_environ=self.env)

        # testing the removal of a channel
        res = self.app.get('/new_channel', headers=headers,
                           extra_environ=self.env)
        cid = str(json.loads(res.body))
        curl = '/%s' % cid
        self.app.delete(curl, headers=headers, extra_environ=self.env)
        self.app.put(curl,  params='somedata', status=404, headers=headers,
                     extra_environ=self.env)
        self.app.get(curl, status=404, headers=headers,
                     extra_environ=self.env)

        # let's try a really small ttl to make sure it works
        if isinstance(self.app.app.cache, dict):
            # memory fallback, bye-bye
            return

        app = self.app.app
        if isinstance(app.cache.cache, MemoryClient):
            return   # TTL is not implemented in the MemoryClient

        app.ttl = 1.
        res = self.app.get('/new_channel', headers=headers,
                           extra_environ=self.env)
        cid = str(json.loads(res.body))
        curl = '/%s' % cid
        self.app.put(curl,  params='somedata', status=200, headers=headers,
                     extra_environ=self.env)

        time.sleep(1.5)

        # should be dead now
        self.app.put(curl,  params='somedata', status=404, headers=headers,
                     extra_environ=self.env)


    def test_id_header(self):
        # all calls must be made with a unique 'X-KeyExchange-Id' header
        # this id must be of length 256

        # no id issues a 400
        self.app.get('/new_channel', status=400, extra_environ=self.env)

        # an id with the wrong size issues a 400
        headers = {'X-KeyExchange-Id': 'boo'}
        self.app.get('/new_channel', headers=headers, status=400,
                     extra_environ=self.env)

        # an id with the right size does the job
        headers = {'X-KeyExchange-Id': 'b' * 256}
        res = self.app.get('/new_channel', headers=headers,
                           extra_environ=self.env)
        cid = str(json.loads(res.body))

        # then we can put stuff as usual in the channel
        curl = '/%s' % cid
        self.app.put(curl, params='somedata', headers=headers,
                     status=200, extra_environ=self.env)

        # another id is used on the other side
        headers2 = {'X-KeyExchange-Id': 'c' * 256}
        self.app.get(curl,  headers=headers2, status=200,
                     extra_environ=self.env)

        # try to get the data with a different id and it's gone
        headers2 = {'X-KeyExchange-Id': 'e' * 256}
        self.app.get(curl,  headers=headers2, status=400,
                     extra_environ=self.env)

        # yes, gone..
        self.app.get(curl, status=404, headers=headers,
                     extra_environ=self.env)


    def test_404s(self):
        # make sure other requests are issuing 404s
        for url in ('/', '/some/url', '/UPER'):
            for method in ('get', 'put', 'post', 'delete'):
                getattr(self.app, method)(url, status=404)
