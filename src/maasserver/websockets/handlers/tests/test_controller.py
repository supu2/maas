# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from maasserver.config import RegionConfiguration
from maasserver.enum import NODE_TYPE
from maasserver.forms import ControllerForm
from maasserver.models import Config, ControllerInfo, VLAN
from maasserver.testing.factory import factory
from maasserver.testing.fixtures import RBACForceOffFixture
from maasserver.testing.testcase import MAASServerTestCase
from maasserver.websockets.base import (
    dehydrate_datetime,
    HandlerPermissionError,
)
from maasserver.websockets.handlers.controller import ControllerHandler
from maastesting.djangotestcase import count_queries
from metadataserver.enum import RESULT_TYPE, SCRIPT_STATUS
from provisioningserver.utils.deb import DebVersionsInfo
from provisioningserver.utils.snap import SnapVersionsInfo


class TestControllerHandler(MAASServerTestCase):
    def make_controllers(self, number):
        """Create `number` of new nodes."""
        for counter in range(number):
            factory.make_RackController()

    def test_vlan_counts_list(self):
        owner = factory.make_admin()
        rack1 = factory.make_RackController(owner=owner)
        rack2 = factory.make_RackController(owner=owner)
        vlan1, vlan2 = VLAN.objects.order_by("id")
        # attach the first rack to both VLANs
        iface = factory.make_Interface(node=rack1, vlan=vlan2)
        factory.make_StaticIPAddress(interface=iface)
        vlan1.primary_rack = rack1
        vlan1.save()
        # make the second VLAN HA
        vlan2.primary_rack = rack2
        vlan2.secondary_rack = rack1
        vlan2.save()

        handler = ControllerHandler(owner, {}, None)
        result = {entry["id"]: entry["vlans_ha"] for entry in handler.list({})}
        self.assertEqual(
            result,
            {
                rack1.id: {"true": 1, "false": 1},
                rack2.id: {"true": 1, "false": 0},
            },
        )

    def test_last_image_sync(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        node = factory.make_RackController(owner=owner)
        result = handler.list({})
        self.assertEqual(1, len(result))
        self.assertEqual(NODE_TYPE.RACK_CONTROLLER, result[0].get("node_type"))
        self.assertEqual(
            result[0].get("last_image_sync"),
            dehydrate_datetime(node.last_image_sync),
        )
        data = handler.get({"system_id": node.system_id})
        self.assertEqual(
            data.get("last_image_sync"),
            dehydrate_datetime(node.last_image_sync),
        )

    def test_last_image_sync_returns_none_for_none(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        node = factory.make_RackController(owner=owner, last_image_sync=None)
        result = handler.list({})
        self.assertEqual(1, len(result))
        self.assertEqual(NODE_TYPE.RACK_CONTROLLER, result[0].get("node_type"))
        self.assertIsNone(result[0].get("last_image_sync"))
        data = handler.get({"system_id": node.system_id})
        self.assertIsNone(data.get("last_image_sync"))

    def test_list_ignores_devices_and_nodes(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        # Create a device.
        factory.make_Node(owner=owner, node_type=NODE_TYPE.DEVICE)
        # Create a device with Node parent.
        node = factory.make_Node(owner=owner)
        device_with_parent = factory.make_Node(owner=owner, interface=True)
        device_with_parent.parent = node
        device_with_parent.save()
        node = factory.make_RackController(owner=owner)
        result = handler.list({})
        self.assertEqual(1, len(result))
        self.assertEqual(NODE_TYPE.RACK_CONTROLLER, result[0].get("node_type"))

    def test_list_num_queries_is_the_expected_number(self):
        self.useFixture(RBACForceOffFixture())

        owner = factory.make_admin()
        for _ in range(10):
            node = factory.make_RegionRackController(owner=owner)
            commissioning_script_set = factory.make_ScriptSet(
                node=node, result_type=RESULT_TYPE.COMMISSIONING
            )
            testing_script_set = factory.make_ScriptSet(
                node=node, result_type=RESULT_TYPE.TESTING
            )
            node.current_commissioning_script_set = commissioning_script_set
            node.current_testing_script_set = testing_script_set
            node.save()
            for __ in range(10):
                factory.make_ScriptResult(
                    status=SCRIPT_STATUS.PASSED,
                    script_set=commissioning_script_set,
                )
                factory.make_ScriptResult(
                    status=SCRIPT_STATUS.PASSED, script_set=testing_script_set
                )

        handler1 = ControllerHandler(owner, {}, None)
        queries_one, _ = count_queries(handler1.list, {"limit": 1})
        handler2 = ControllerHandler(owner, {}, None)
        queries_all, _ = count_queries(handler2.list, {})
        # This check is to notify the developer that a change was made that
        # affects the number of queries performed when doing a node listing.
        # It is important to keep this number as low as possible. A larger
        # number means regiond has to do more work slowing down its process
        # and slowing down the client waiting for the response.
        # The test uses different handler instances as some query results are
        # cached between calls.
        self.assertEqual(
            queries_one,
            queries_all,
            "Number of queries has changed; make sure this is expected.",
        )

    def test_get_num_queries_is_the_expected_number(self):
        owner = factory.make_admin()
        node = factory.make_RegionRackController(owner=owner)
        commissioning_script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.COMMISSIONING
        )
        testing_script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.TESTING
        )
        node.current_commissioning_script_set = commissioning_script_set
        node.current_testing_script_set = testing_script_set
        node.save()
        for __ in range(10):
            factory.make_ScriptResult(
                status=SCRIPT_STATUS.PASSED,
                script_set=commissioning_script_set,
            )
            factory.make_ScriptResult(
                status=SCRIPT_STATUS.PASSED, script_set=testing_script_set
            )

        handler = ControllerHandler(owner, {}, None)
        queries, _ = count_queries(handler.get, {"system_id": node.system_id})
        # This check is to notify the developer that a change was made that
        # affects the number of queries performed when doing a node get.
        # It is important to keep this number as low as possible. A larger
        # number means regiond has to do more work slowing down its process
        # and slowing down the client waiting for the response.
        self.assertEqual(
            queries,
            35,
            "Number of queries has changed; make sure this is expected.",
        )

    def test_get_form_class_for_create(self):
        user = factory.make_admin()
        handler = ControllerHandler(user, {}, None)
        self.assertEqual(ControllerForm, handler.get_form_class("create"))

    def test_get_form_class_for_update(self):
        user = factory.make_admin()
        handler = ControllerHandler(user, {}, None)
        self.assertEqual(ControllerForm, handler.get_form_class("update"))

    def test_update_uses_handler_queryset(self):
        # test for lp:1927292
        user = factory.make_admin()
        handler = ControllerHandler(user, {}, None)
        controller = factory.make_RackController()
        data = handler.get({"system_id": controller.system_id})
        updated = handler.update(data)
        self.assertIn("vlans_ha", updated)

    def test_check_images(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        node1 = factory.make_RackController(owner=owner)
        node2 = factory.make_RackController(owner=owner)
        data = handler.check_images(
            [{"system_id": node1.system_id}, {"system_id": node2.system_id}]
        )
        self.assertEqual(
            {node1.system_id: "Unknown", node2.system_id: "Unknown"}, data
        )

    def test_dehydrate_show_os_info_returns_true(self):
        owner = factory.make_admin()
        rack = factory.make_RackController()
        handler = ControllerHandler(owner, {}, None)
        self.assertTrue(handler.dehydrate_show_os_info(rack))

    def test_dehydrate_empty_versions(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        factory.make_RackController()
        result = handler.list({})
        self.assertEqual(result[0]["versions"], {})

    def test_dehydrate_with_versions_snap(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        rack = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            channel={"track": "3.0", "risk": "stable"},
            update={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
            cohort="abc123",
        )
        ControllerInfo.objects.set_versions_info(rack, versions)
        result = handler.list({})
        self.assertEqual(
            result[0]["versions"],
            {
                "install_type": "snap",
                "current": {
                    "version": "3.0.0~alpha1-111-g.deadbeef",
                    "snap_revision": "1234",
                },
                "update": {
                    "version": "3.0.0~alpha2-222-g.cafecafe",
                    "snap_revision": "5678",
                },
                "origin": "3.0/stable",
                "snap_cohort": "abc123",
                "up_to_date": False,
                "issues": [],
            },
        )

    def test_dehydrate_with_versions_deb(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        rack = factory.make_RackController()
        versions = DebVersionsInfo(
            current={
                "version": "3.0.0~alpha1-111-g.deadbeef",
                "origin": "http://archive.ubuntu.com main/focal",
            },
            update={
                "version": "3.0.0~alpha2-222-g.cafecafe",
                "origin": "http://archive.ubuntu.com main/focal",
            },
        )
        ControllerInfo.objects.set_versions_info(rack, versions)
        result = handler.list({})
        self.assertEqual(
            result[0]["versions"],
            {
                "install_type": "deb",
                "current": {
                    "version": "3.0.0~alpha1-111-g.deadbeef",
                },
                "update": {
                    "version": "3.0.0~alpha2-222-g.cafecafe",
                },
                "origin": "http://archive.ubuntu.com main/focal",
                "up_to_date": False,
                "issues": [],
            },
        )

    def test_dehydrate_with_versions_only_current(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        rack = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            channel={"track": "3.0", "risk": "stable"},
        )
        ControllerInfo.objects.set_versions_info(rack, versions)
        result = handler.list({})
        self.assertEqual(
            result[0]["versions"],
            {
                "install_type": "snap",
                "current": {
                    "version": "3.0.0~alpha1-111-g.deadbeef",
                    "snap_revision": "1234",
                },
                "origin": "3.0/stable",
                "up_to_date": True,
                "issues": [],
            },
        )

    def test_dehydrate_not_up_to_date_no_update(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        rack = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            channel={"track": "3.0", "risk": "stable"},
        )
        ControllerInfo.objects.set_versions_info(rack, versions)
        # another rack as a higher version
        ControllerInfo.objects.set_versions_info(
            factory.make_RackController(),
            SnapVersionsInfo(
                current={
                    "revision": "1234",
                    "version": "3.0.0-222-g.cafecafe",
                },
                channel={"track": "3.0", "risk": "stable"},
            ),
        )
        result = handler.list({})
        self.assertEqual(
            result[0]["versions"],
            {
                "install_type": "snap",
                "current": {
                    "version": "3.0.0~alpha1-111-g.deadbeef",
                    "snap_revision": "1234",
                },
                "origin": "3.0/stable",
                "up_to_date": False,
                "issues": [],
            },
        )

    def test_dehydrate_with_versions_issues(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        rack = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            channel={"track": "3.0", "risk": "stable"},
            cohort="abc",
        )
        ControllerInfo.objects.set_versions_info(rack, versions)
        # another rack with a higher version has no cohort
        ControllerInfo.objects.set_versions_info(
            factory.make_RackController(),
            SnapVersionsInfo(
                current={
                    "revision": "5678",
                    "version": "3.0.0-222-g.cafecafe",
                },
                channel={"track": "3.0", "risk": "stable"},
            ),
        )
        versions = handler.list({})[0]["versions"]
        self.assertEqual(versions["issues"], ["different-cohort"])

    def test_dehydrate_with_versions_empty_origin(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        rack = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
        )
        ControllerInfo.objects.set_versions_info(rack, versions)
        result = handler.list({})
        self.assertEqual(result[0]["versions"]["origin"], "")

    def test_dehydrate_includes_tags(self):
        owner = factory.make_admin()
        handler = ControllerHandler(owner, {}, None)
        region = factory.make_RegionRackController()
        tags = []
        for _ in range(3):
            tag = factory.make_Tag(definition="")
            tag.node_set.add(region)
            tag.save()
            tags.append(tag.name)
        result = handler.list({})
        self.assertEqual(tags, result[0].get("tags"))

    def test_register_info_non_admin(self):
        user = factory.make_User()
        handler = ControllerHandler(user, {}, None)
        self.assertRaises(HandlerPermissionError, handler.register_info, {})

    def test_register_info(self):
        admin = factory.make_admin()
        handler = ControllerHandler(admin, {}, None)
        observed = handler.register_info({})
        rpc_shared_secret = Config.objects.get_config("rpc_shared_secret")
        with RegionConfiguration.open() as config:
            maas_url = config.maas_url
        self.assertEqual(
            {"url": maas_url, "secret": rpc_shared_secret}, observed
        )
