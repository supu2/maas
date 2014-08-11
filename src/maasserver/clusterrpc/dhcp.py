# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""DHCP related RPC helpers."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

from collections import defaultdict
from functools import partial

from maasserver.models.dhcplease import DHCPLease
from netaddr import (
    IPAddress,
    IPRange,
    )
from provisioningserver.rpc.cluster import (
    CreateHostMaps,
    RemoveHostMaps,
    )


def gen_calls_to_create_host_maps(clients, static_mappings):
    """Generate calls to create host maps in clusters' DHCP servers.

    :param clients: A mapping of cluster UUIDs to
        :py:class:`~provisioningserver.rpc.common.Client` instances.
        There must be a client for each nodegroup in the
        `static_mappings` argument.
    :param static_mappings: A mapping from `NodeGroup` model instances
        to mappings of ``ip-address -> mac-address``.
    :return: A generator of callables.
    """
    make_mappings_for_call = lambda mappings: [
        {"ip_address": ip_address, "mac_address": mac_address}
        for ip_address, mac_address in mappings.viewitems()
    ]
    for nodegroup, mappings in static_mappings.viewitems():
        yield partial(
            clients[nodegroup], CreateHostMaps,
            mappings=make_mappings_for_call(mappings),
            shared_key=nodegroup.dhcp_key)


def gen_dynamic_ip_addresses_with_host_maps(static_mappings):
    """Generate leased IP addresses that are safe to remove.

    They're safe to remove because they lie outside of all of their cluster's
    static ranges, and are thus no longer officially managed. In most cases
    these will be leftover host maps in the dynamic range that wouldn't have
    worked anyway.

    :param static_mappings: A mapping from `NodeGroup` model instances
        to mappings of ``ip-address -> mac-address``.
    :return: A generator of ``(nodegroup, ip-address)`` tuples.
    """
    for nodegroup, mappings in static_mappings.viewitems():
        managed_ranges = tuple(
            IPRange(ngi.static_ip_range_low, ngi.static_ip_range_high)
            for ngi in nodegroup.get_managed_interfaces())
        dhcp_leases = DHCPLease.objects.filter(
            nodegroup=nodegroup, mac__in=mappings.viewvalues())
        for dhcp_lease in dhcp_leases:
            dhcp_lease_ip = IPAddress(dhcp_lease.ip)
            within_managed_range = any(
                dhcp_lease_ip in static_range
                for static_range in managed_ranges)
            if not within_managed_range:
                yield nodegroup, dhcp_lease.ip


def gen_calls_to_remove_dynamic_host_maps(clients, static_mappings):
    """Generates calls to remove old dynamic leases.

    See `gen_dynamic_ip_addresses_with_host_maps` for the source of the leases
    to remove.

    :param clients: A mapping of cluster UUIDs to
        :py:class:`~provisioningserver.rpc.common.Client` instances.
        There must be a client for each nodegroup in the
        `static_mappings` argument.
    :param static_mappings: A mapping from `NodeGroup` model instances
        to mappings of ``ip-address -> mac-address``.
    :return: A generator of callables.
    """
    ip_addresses_to_remove = defaultdict(set)
    ip_addresses_with_maps = (
        gen_dynamic_ip_addresses_with_host_maps(static_mappings))
    for nodegroup, ip_address in ip_addresses_with_maps:
        ip_addresses_to_remove[nodegroup].add(ip_address)
    for nodegroup, ip_addresses in ip_addresses_to_remove.viewitems():
        yield partial(
            clients[nodegroup], RemoveHostMaps, ip_addresses=ip_addresses,
            shared_key=nodegroup.dhcp_key)
