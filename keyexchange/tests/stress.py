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
import time
import hashlib

from keyexchange.tests import _patch

from funkload.FunkLoadTestCase import FunkLoadTestCase
from funkload.utils import Data


class StressTest(FunkLoadTestCase):

    def setUp(self):
        self.root = self.conf_get('main', 'url')

    def test_basic_usage(self):
        hash = hashlib.sha256(str(random.randint(1, 1000))).hexdigest()
        self.setHeader('X-KeyExchange-Id', hash * 4)
        res = self.get(self.root + '/new_channel')
        cid = str(json.loads(res.body))
        curl = self.root + '/' + cid
        data = json.dumps('*' * 200)
        self.put(curl, Data('application/json', data))
        res = self.get(curl)
        self.assertEquals(res.body, data)

    def test_DoS(self):
        hash = hashlib.sha256(str(random.randint(1, 1000))).hexdigest()
        self.setHeader('X-KeyExchange-Id', hash * 4)
        for i in range(100):
            try:
                self.get(self.root + '/new_channel')
            except Exception, e:
                if '500' not in str(e):
                    raise


if __name__ == '__main__':
    unittest.main()
