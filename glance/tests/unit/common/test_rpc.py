# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- coding: utf-8 -*-

# Copyright 2013 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import json

import mox
from oslo.config import cfg
import routes
import webob

from glance.common import rpc
from glance.common import wsgi
from glance.tests.unit import base
from glance.tests import utils as test_utils

CONF = cfg.CONF


class FakeResource(object):
    """
    Fake resource defining some methods that
    will be called later by the api.
    """

    def get_images(self, context, keyword=None):
        return keyword

    def get_all_images(self, context):
        return False

    def raise_value_error(self, context):
        raise ValueError("Yep, Just like that!")

    def raise_weird_error(self, context):
        class WeirdError(Exception):
            pass
        raise WeirdError("Weirdness")


def create_api():
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    controller = rpc.Controller()
    controller.register(FakeResource())
    res = wsgi.Resource(controller, deserializer, serializer)

    mapper = routes.Mapper()
    mapper.connect("/rpc", controller=res,
                   conditions=dict(method=["POST"]),
                   action="__call__")
    return test_utils.FakeAuthMiddleware(wsgi.Router(mapper), is_admin=True)


class TestRPCController(base.IsolatedUnitTest):

    def setUp(self):
        super(TestRPCController, self).setUp()
        self.res = FakeResource()
        self.controller = rpc.Controller()
        self.controller.register(self.res)

        # Mock
        self.mocker = mox.Mox()

    def test_register(self):
        res = FakeResource()
        controller = rpc.Controller()
        controller.register(res)
        self.assertIn("get_images", controller._registered)
        self.assertIn("get_all_images", controller._registered)

    def test_reigster_filtered(self):
        res = FakeResource()
        controller = rpc.Controller()
        controller.register(res, filtered=["get_all_images"])
        self.assertIn("get_all_images", controller._registered)

    def test_reigster_excluded(self):
        res = FakeResource()
        controller = rpc.Controller()
        controller.register(res, excluded=["get_all_images"])
        self.assertIn("get_images", controller._registered)

    def test_reigster_refiner(self):
        res = FakeResource()
        controller = rpc.Controller()

        # Not callable
        self.assertRaises(AssertionError,
                          controller.register,
                          res, refiner="get_all_images")

        # Filter returns False
        controller.register(res, refiner=lambda x: False)
        self.assertNotIn("get_images", controller._registered)
        self.assertNotIn("get_images", controller._registered)

        # Filter returns True
        controller.register(res, refiner=lambda x: True)
        self.assertIn("get_images", controller._registered)
        self.assertIn("get_images", controller._registered)

    def test_request(self):
        api = create_api()
        req = webob.Request.blank('/rpc')
        req.method = 'POST'
        req.body = json.dumps([
            {
                "command": "get_images",
                "kwargs": {"keyword": 1}
            }
        ])
        res = req.get_response(api)
        returned = json.loads(res.body)
        self.assertTrue(isinstance(returned, list))
        self.assertEquals(returned[0], 1)

    def test_request_exc(self):
        api = create_api()
        req = webob.Request.blank('/rpc')
        req.method = 'POST'
        req.body = json.dumps([
            {
                "command": "get_all_images",
                "kwargs": {"keyword": 1}
            }
        ])

        # Sending non-accepted keyword
        # to get_all_images method
        res = req.get_response(api)
        returned = json.loads(res.body)
        self.assertIn("_error", returned[0])

    def test_rpc_errors(self):
        api = create_api()
        req = webob.Request.blank('/rpc')
        req.method = 'POST'
        req.content_type = 'application/json'

        # Body is not a list, it should fail
        req.body = json.dumps({})
        res = req.get_response(api)
        self.assertEquals(res.status_int, 400)

        # cmd is not dict, it should fail.
        req.body = json.dumps([None])
        res = req.get_response(api)
        self.assertEquals(res.status_int, 400)

        # No command key, it should fail.
        req.body = json.dumps([{}])
        res = req.get_response(api)
        self.assertEquals(res.status_int, 400)

        # kwargs not dict, it should fail.
        req.body = json.dumps([{"command": "test", "kwargs": 200}])
        res = req.get_response(api)
        self.assertEquals(res.status_int, 400)

        # Command does not exist, it should fail.
        req.body = json.dumps([{"command": "test"}])
        res = req.get_response(api)
        self.assertEquals(res.status_int, 404)

    def test_rpc_exception_propagation(self):
        api = create_api()
        req = webob.Request.blank('/rpc')
        req.method = 'POST'
        req.content_type = 'application/json'

        req.body = json.dumps([{"command": "raise_value_error"}])
        res = req.get_response(api)
        self.assertEquals(res.status_int, 200)

        returned = json.loads(res.body)[0]
        self.assertEquals(returned['_error']['cls'], 'exceptions.ValueError')

        req.body = json.dumps([{"command": "raise_weird_error"}])
        res = req.get_response(api)
        self.assertEquals(res.status_int, 200)

        returned = json.loads(res.body)[0]
        self.assertEquals(returned['_error']['cls'],
                          'glance.common.exception.RPCError')