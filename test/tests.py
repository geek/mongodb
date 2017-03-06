"""
Integration tests for autopilotpattern/mongodb. These tests are executed
inside a test-running container based on autopilotpattern/testing.
"""
from __future__ import print_function
import os
from os.path import expanduser
import random
import subprocess
import string
import sys
import time
import unittest
import uuid

from testcases import AutopilotPatternTest, WaitTimeoutError, dump_environment_to_file


class MongodbStackTest(AutopilotPatternTest):

    project_name = 'mongodb'

    def setUp(self):
        """
        autopilotpattern/mongodb setup.sh writes an _env file with a CNS
        entry and account info for Manta. If this has been mounted from
        the test environment, we'll use that, otherwise we have to
        generate it from the environment.
        """
        if not os.path.isfile('_env'):
            print('generating _env')
            with open(os.environ['DOCKER_CERT_PATH'] + '/key.pem') as key_file:
                manta_key = '#'.join([line.strip() for line in key_file])
            os.environ['MANTA_PRIVATE_KEY'] = manta_key

            dump_environment_to_file('_env')

    def test_replication_and_failover(self):
        """
        Given the MongoDB stack, when we scale up MongoDB instances they should:
        - become a new replica
        - with working replication
        Given when we stop the MongoDB primary:
        - one of the replicas should become the new primary
        - the other replica should replicate from it
        """
        # wait until the first instance has configured itself as the
        # the primary; we need very long timeout b/c of provisioning
        self.settle('mongodb-primary', 1, timeout=600)

        # scale up, make sure we have 2 working replica instances
        self.compose_scale('mongodb', 3)
        self.settle('mongodb', 2, timeout=600)

        # create a collection
        create_collection = 'db.createCollection("collection1")'
        self.exec_query('mongodb_1', create_collection)

        # check replication is working by writing documents to the primary
        # and verifying they show up in the replicas

        insert_documents = 'db.collection1.insert([{ val1: {}, val2: "{}" }])'

        vals = [str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4())]

        self.exec_query('mongodb_1', insert_documents.format(1, vals[0]))
        self.exec_query('mongodb_1', insert_documents.format(1, vals[1]))
        self.assert_good_replication(vals[:2])

        # kill the primary, make sure we get a new primary
        self.docker_stop('mongodb_1')
        self.settle('mongodb-primary', 1, timeout=300)
        self.settle('mongodb', 1)

        # check replication is still working
        primary = self.get_service_instances_from_consul('mongodb-primary')[0]
        self.exec_query(primary, insert_documents.format(1, vals[2]))
        self.assert_good_replication(vals)

    def settle(self, service, count, timeout=60):
        """
        Wait for the service to appear healthy and correctly in Consul
        """
        try:
            nodes = self.instrument(self.wait_for_service,
                                    service, count, timeout=timeout)
            if len(nodes) < count:
                raise WaitTimeoutError()
            self.instrument(self.assert_consul_correctness)
        except WaitTimeoutError:
            self.fail('Failed to scale {} to {} instances'
                      .format(service, count))

    def assert_consul_correctness(self):
        """ Verify that Consul addresses match container addresses """
        try:
            primary = self.get_primary_ip()
            replicas = self.get_replica_ips()
            expected = [str(ip) for ip in
                        self.get_service_ips('mongodb', ignore_errors=True)[1]]
        except subprocess.CalledProcessError as ex:
            self.fail('subprocess.CalledProcessError: {}'.format(ex.output))
        expected.remove(primary)
        expected.sort()
        self.assertEqual(replicas, expected,
                         'Upstream blocks {} did not match actual IPs {}'
                         .format(replicas, expected))

    def assert_good_replication(self, expected_vals):
        """
        Checks each replica to make sure it has the recently written
        val1 passed in as the `vals` param.
        """
        check_document = 'db.collection1.findOne("val1": 1)'

        def check_replica(replica):
            timeout = 15
            while timeout > 0:
                # we'll give the replica a couple chances to catch up
                results = self.exec_query(replica, check_document).splitlines()
                got_vals = []
                for line in results:
                    if line.startswith('val2:'):
                        got_vals.append(line.replace('val1: ', '', 1))
                    if not set(expected_vals) - set(got_vals):
                        return None # all values replicated

                # we're missing a value
                timeout -= 1
            return got_vals

        replicas = self.get_replica_containers()
        for replica in replicas:
            got_vals = check_replica(replica)
            if got_vals:
                self.fail('Replica {} is missing values {}; got {}'
                          .format(replica, expected_vals, got_vals))

    def get_primary_ip(self):
        """ Get the IP for the primary from Consul. """
        try:
            node = self.get_service_addresses_from_consul('mongodb-primary')[0]
            return node
        except IndexError:
            self.fail('mongodb-primary does not exist in Consul.')

    def get_replica_ips(self):
        """ Get the IPs for the replica(s) from Consul. """
        nodes = self.get_service_addresses_from_consul('mongodb')
        nodes.sort()
        return nodes

    def get_primary_container(self):
        """ Get the container name for the primary from Consul """
        try:
            node = self.get_service_instances_from_consul('mongodb-primary')[0]
            return node
        except IndexError:
            self.fail('mongodb-primary does not exist in Consul.')

    def get_replica_containers(self):
        """ Get the container names for the replica(s) from Consul. """
        nodes = self.get_service_instances_from_consul('mongodb')
        nodes.sort()
        return nodes

    def exec_query(self, container, query, user=None, passwd=None):
        """
        Runs MongoDB statement via docker exec.
        """
        if not user:
            user = self.user
        if not passwd:
            passwd = self.passwd
        cmd = ['mongo', self.db,
               '--eval', query]
        try:
            out = self.docker_exec(container, cmd)
        except subprocess.CalledProcessError as ex:
            self.fail('subprocess.CalledProcessError in {} for command {}:\n{}'
                      .format(container, cmd, ex.output))
        return out



if __name__ == "__main__":
    unittest.main(failfast=True)
