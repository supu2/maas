# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import random

from django.http import Http404

from maasserver.models.virtualmachine import MB
from maasserver.models.vmcluster import VMCluster
from maasserver.permissions import VMClusterPermission
from maasserver.testing.factory import factory
from maasserver.testing.fixtures import RBACEnabled
from maasserver.testing.testcase import MAASServerTestCase


class TestVMClusterManager(MAASServerTestCase):
    def enable_rbac(self):
        rbac = self.useFixture(RBACEnabled())
        self.store = rbac.store

    def test_group_by_physical_cluster(self):
        user = factory.make_User()
        cluster_groups = [
            [factory.make_VMCluster(pods=0) for _ in range(3)]
            for _ in range(3)
        ]

        for i, cluster_group in enumerate(cluster_groups):
            address_group = [factory.make_StaticIPAddress() for _ in range(3)]
            for cluster in cluster_group:
                for address in address_group:
                    factory.make_Pod(
                        cluster=cluster,
                        parameters={
                            "project": cluster.project,
                            "power_address": "%s:8443" % address,
                        },
                        pod_type="lxd",
                    )

        results = VMCluster.objects.group_by_physical_cluster(user)
        self.assertCountEqual(results, cluster_groups)

    def test_group_by_physical_cluster_with_rbac(self):
        self.enable_rbac()
        user = factory.make_User()
        view_pool = factory.make_ResourcePool()
        self.store.add_pool(view_pool)
        self.store.allow(user.username, view_pool, "view")
        view_all_pool = factory.make_ResourcePool()
        self.store.add_pool(view_all_pool)
        self.store.allow(user.username, view_all_pool, "view-all")
        view_cluster_group = [
            factory.make_VMCluster(pool=view_pool, pods=0) for _ in range(3)
        ]
        view_all_cluster_group = [
            factory.make_VMCluster(pool=view_all_pool, pods=0)
            for _ in range(3)
        ]
        other_cluster_group = [
            factory.make_VMCluster(pods=0) for _ in range(3)
        ]
        cluster_groups = [
            view_cluster_group,
            view_all_cluster_group,
            other_cluster_group,
        ]
        for i, cluster_group in enumerate(cluster_groups):
            address_group = [factory.make_StaticIPAddress() for _ in range(3)]
            for cluster in cluster_group:
                for address in address_group:
                    factory.make_Pod(
                        cluster=cluster,
                        parameters={
                            "project": cluster.project,
                            "power_address": "%s:8443" % address,
                        },
                        pod_type="lxd",
                    )

        results = VMCluster.objects.group_by_physical_cluster(user)
        self.assertCountEqual(
            results, [view_cluster_group, view_all_cluster_group]
        )

    def test_get_cluster_or_404_returns_cluster(self):
        username = factory.make_name("name")
        user = factory.make_User(username=username)
        cluster = factory.make_VMCluster()
        result = VMCluster.objects.get_cluster_or_404(
            cluster.id, user, VMClusterPermission.view
        )
        self.assertEqual(result, cluster)

    def test_get_cluster_or_404_returns_404_for_non_existent_cluster(self):
        username = factory.make_name("name")
        user = factory.make_User(username=username)
        self.assertRaises(
            Http404,
            VMCluster.objects.get_cluster_or_404,
            -1,
            user,
            VMClusterPermission.view,
        )

    def test_get_clusters_returns_view_rights(self):
        self.enable_rbac()
        user = factory.make_User()
        view_pool = factory.make_ResourcePool()
        view_cluster = factory.make_VMCluster(pool=view_pool)
        self.store.add_pool(view_pool)
        self.store.allow(user.username, view_pool, "view")
        view_all_pool = factory.make_ResourcePool()
        view_all_cluster = factory.make_VMCluster(pool=view_all_pool)
        self.store.add_pool(view_all_pool)
        self.store.allow(user.username, view_all_pool, "view-all")

        for _ in range(3):
            factory.make_VMCluster()

        self.assertCountEqual(
            [view_cluster, view_all_cluster],
            VMCluster.objects.get_clusters(user, VMClusterPermission.view),
        )


class TestVMCluster(MAASServerTestCase):
    def test_hosts(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        pods = []
        for _ in range(0, 3):
            pods.append(
                factory.make_Pod(
                    pod_type="lxd", host=factory.make_Node(), cluster=cluster
                )
            )

        hosts = list(cluster.hosts())

        for pod in pods:
            self.assertIn(pod, hosts)

    def test_allocated_total_resources(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        storage_total = 0
        storage_allocated = 0

        for _ in range(0, 3):
            pod = factory.make_Pod(
                pod_type="lxd",
                host=None,
                cores=8,
                memory=4096,
                cluster=cluster,
            )
            pool_name = factory.make_name("pool")
            pool1 = factory.make_PodStoragePool(pod=pod, name=pool_name)
            storage_total += pool1.storage
            node = factory.make_Node(bmc=pod)
            vm = factory.make_VirtualMachine(
                machine=node,
                memory=1024,
                pinned_cores=[0, 2],
                hugepages_backed=False,
                bmc=pod,
            )
            disk1 = factory.make_VirtualMachineDisk(vm=vm, backing_pool=pool1)
            storage_allocated += disk1.size

        resources = cluster.total_resources()
        self.assertEqual(resources.cores.allocated, 6)
        self.assertEqual(resources.cores.free, 18)
        self.assertEqual(resources.cores.overcommited, 24)
        self.assertEqual(resources.memory.general.free, 9216 * MB)
        self.assertEqual(resources.memory.general.allocated, 3072 * MB)
        self.assertEqual(resources.memory.general.overcommited, 12288 * MB)
        self.assertEqual(resources.memory.hugepages.free, 0)
        self.assertEqual(resources.memory.hugepages.allocated, 0)
        self.assertEqual(resources.storage.allocated, storage_allocated)
        for pool in resources.storage_pools.values():
            self.assertEqual(pool.shared, False)

        self.assertEqual(
            resources.storage.free, storage_total - storage_allocated
        )

    def test_allocated_total_resources_shared_pool(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        storage_allocated = 0
        storage_total = random.randint(10 * 1024 ** 3, 100 * 1024 ** 3)
        pool_name = factory.make_name("pool")

        for _ in range(0, 3):
            pod = factory.make_Pod(
                pod_type="lxd",
                host=None,
                cores=8,
                memory=4096,
                cluster=cluster,
            )
            node = factory.make_Node(bmc=pod)
            vm = factory.make_VirtualMachine(
                machine=node,
                memory=1024,
                pinned_cores=[0, 2],
                hugepages_backed=False,
                bmc=pod,
            )
            pool1 = factory.make_PodStoragePool(
                pod=pod,
                name=pool_name,
                pool_type="ceph",
                storage=storage_total,
            )
            disk_size = random.randint(1 * 1024 ** 3, storage_total // 3)
            factory.make_VirtualMachineDisk(
                vm=vm, backing_pool=pool1, size=disk_size
            )
            storage_allocated += disk_size

        resources = cluster.total_resources()
        self.assertEqual(resources.cores.allocated, 6)
        self.assertEqual(resources.cores.free, 18)
        self.assertEqual(resources.memory.general.free, 9216 * MB)
        self.assertEqual(resources.memory.general.allocated, 3072 * MB)
        self.assertEqual(resources.memory.hugepages.free, 0)
        self.assertEqual(resources.memory.hugepages.allocated, 0)
        self.assertEqual(resources.storage.allocated, storage_allocated)
        self.assertEqual(resources.storage_pools[pool_name].shared, True)
        self.assertEqual(
            resources.storage_pools[pool_name].allocated, storage_allocated
        )
        self.assertEqual(
            resources.storage_pools[pool_name].total, storage_total
        )
        self.assertEqual(
            resources.storage.free, storage_total - storage_allocated
        )

    def test_allocated_total_resources_mixed_pool(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        storage_shared_allocated = 0
        storage_shared_total = random.randint(10 * 1024 ** 3, 100 * 1024 ** 3)
        storage_nonshared_allocated = 0
        storage_nonshared_total = 0
        pool_shared_name = factory.make_name("pool-ceph")
        pool_nonshared_name = factory.make_name("pool-lvm")

        for _ in range(0, 3):
            pod = factory.make_Pod(
                pod_type="lxd",
                host=None,
                cores=8,
                memory=4096,
                cluster=cluster,
            )
            node = factory.make_Node(bmc=pod)
            vm = factory.make_VirtualMachine(
                machine=node,
                memory=1024,
                pinned_cores=[0, 2],
                hugepages_backed=False,
                bmc=pod,
            )
            pool1 = factory.make_PodStoragePool(
                pod=pod,
                name=pool_shared_name,
                pool_type="ceph",
                storage=storage_shared_total,
            )
            disk_size = random.randint(
                1 * 1024 ** 3, storage_shared_total // 3
            )
            factory.make_VirtualMachineDisk(
                vm=vm, backing_pool=pool1, size=disk_size
            )
            storage_shared_allocated += disk_size
            pool2 = factory.make_PodStoragePool(
                pod=pod, name=pool_nonshared_name, pool_type="lvm"
            )
            storage_nonshared_total += pool2.storage
            disk_size = random.randint(1 * 1024 ** 3, pool2.storage)
            factory.make_VirtualMachineDisk(
                vm=vm, backing_pool=pool2, size=disk_size
            )
            storage_nonshared_allocated += disk_size

        resources = cluster.total_resources()
        self.assertEqual(resources.cores.allocated, 6)
        self.assertEqual(resources.cores.free, 18)
        self.assertEqual(resources.memory.general.free, 9216 * MB)
        self.assertEqual(resources.memory.general.allocated, 3072 * MB)
        self.assertEqual(resources.memory.hugepages.free, 0)
        self.assertEqual(resources.memory.hugepages.allocated, 0)
        self.assertEqual(
            resources.storage_pools[pool_nonshared_name].shared, False
        )
        self.assertEqual(
            resources.storage_pools[pool_nonshared_name].allocated,
            storage_nonshared_allocated,
        )
        self.assertEqual(
            resources.storage_pools[pool_nonshared_name].total,
            storage_nonshared_total,
        )
        self.assertEqual(
            resources.storage_pools[pool_shared_name].shared, True
        )
        self.assertEqual(
            resources.storage_pools[pool_shared_name].allocated,
            storage_shared_allocated,
        )
        self.assertEqual(
            resources.storage_pools[pool_shared_name].total,
            storage_shared_total,
        )

        self.assertEqual(
            resources.storage.allocated,
            storage_shared_allocated + storage_nonshared_allocated,
        )
        self.assertEqual(
            resources.storage.free,
            storage_nonshared_total
            + storage_shared_total
            - storage_shared_allocated
            - storage_nonshared_allocated,
        )

    def test_no_allocated_total_resources(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        for _ in range(0, 3):
            pod = factory.make_Pod(
                pod_type="lxd",
                host=None,
                cores=8,
                memory=4096,
                cluster=cluster,
            )
            factory.make_Node(bmc=pod)

        resources = cluster.total_resources()
        self.assertEqual(resources.cores.allocated, 0)
        self.assertEqual(resources.cores.free, 24)
        self.assertEqual(resources.memory.general.free, 3 * 4096 * MB)
        self.assertEqual(resources.memory.general.allocated, 0)
        self.assertEqual(resources.memory.hugepages.free, 0)
        self.assertEqual(resources.memory.hugepages.allocated, 0)
        self.assertEqual(resources.storage.allocated, 0)
        self.assertEqual(resources.storage.free, 0)

    def test_no_hosts_total_resources(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        resources = cluster.total_resources()
        self.assertEqual(resources.cores.allocated, 0)
        self.assertEqual(resources.cores.free, 0)
        self.assertEqual(resources.memory.general.free, 0)
        self.assertEqual(resources.memory.general.allocated, 0)
        self.assertEqual(resources.memory.hugepages.free, 0)
        self.assertEqual(resources.memory.hugepages.allocated, 0)
        self.assertEqual(resources.storage.allocated, 0)
        self.assertEqual(resources.storage.free, 0)

    def test_get_storage_pools(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        storage_shared_allocated = 0
        storage_shared_total = random.randint(10 * 1024 ** 3, 100 * 1024 ** 3)
        storage_nonshared_allocated = 0
        storage_nonshared_total = 0
        pool_shared_name = factory.make_name("pool-ceph")
        pool_nonshared_name = factory.make_name("pool-lvm")

        for _ in range(0, 3):
            pod = factory.make_Pod(
                pod_type="lxd",
                host=None,
                cores=8,
                memory=4096,
                cluster=cluster,
            )
            node = factory.make_Node(bmc=pod)
            vm = factory.make_VirtualMachine(
                machine=node,
                memory=1024,
                pinned_cores=[0, 2],
                hugepages_backed=False,
                bmc=pod,
            )
            pool1 = factory.make_PodStoragePool(
                pod=pod,
                name=pool_shared_name,
                pool_type="ceph",
                storage=storage_shared_total,
            )
            disk_size = random.randint(
                1 * 1024 ** 3, storage_shared_total // 3
            )
            factory.make_VirtualMachineDisk(
                vm=vm, backing_pool=pool1, size=disk_size
            )
            storage_shared_allocated += disk_size
            pool2 = factory.make_PodStoragePool(
                pod=pod, name=pool_nonshared_name, pool_type="lvm"
            )
            storage_nonshared_total += pool2.storage
            disk_size = random.randint(1 * 1024 ** 3, pool2.storage)
            factory.make_VirtualMachineDisk(
                vm=vm, backing_pool=pool2, size=disk_size
            )
            storage_nonshared_allocated += disk_size

        cluster_pools = cluster.storage_pools()
        self.assertEqual(cluster_pools[pool_nonshared_name].shared, False)
        self.assertEqual(
            cluster_pools[pool_nonshared_name].allocated,
            storage_nonshared_allocated,
        )
        self.assertEqual(
            cluster_pools[pool_nonshared_name].total,
            storage_nonshared_total,
        )
        self.assertEqual(cluster_pools[pool_shared_name].shared, True)
        self.assertEqual(
            cluster_pools[pool_shared_name].allocated,
            storage_shared_allocated,
        )
        self.assertEqual(
            cluster_pools[pool_shared_name].total,
            storage_shared_total,
        )

    def test_virtual_machines(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        expected_vms = []
        for _ in range(0, 3):
            pod = factory.make_Pod(
                pod_type="lxd",
                host=None,
                cores=8,
                memory=4096,
                cluster=cluster,
            )
            node = factory.make_Node(bmc=pod)
            expected_vms.append(
                factory.make_VirtualMachine(
                    machine=node,
                    memory=1024,
                    pinned_cores=[0, 2],
                    hugepages_backed=False,
                    bmc=pod,
                )
            )

        self.assertCountEqual(cluster.virtual_machines(), expected_vms)

    def test_virtual_machines_hosts_no_vms(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        for _ in range(0, 3):
            pod = factory.make_Pod(
                pod_type="lxd",
                host=None,
                cores=8,
                memory=4096,
                cluster=cluster,
            )
            factory.make_Node(bmc=pod)
        self.assertEqual(list(cluster.virtual_machines()), [])

    def test_virtual_machines_no_hosts(self):
        cluster_name = factory.make_name("name")
        project = factory.make_name("project")
        cluster = VMCluster(name=cluster_name, project=project)
        self.assertEqual(list(cluster.virtual_machines()), [])
