# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import call, patch

from zaza.charm_lifecycle.test import run_direct_with_args
from zaza.charm_tests.lifecycle import refresh


class TestCharmRefreshAll(unittest.TestCase):

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.charm = self.directory / 'ceph-osd.charm'
        self.charm.touch()
        self.helper = refresh.CharmRefreshAll()
        for target, attribute in [
                ('subprocess.check_call', 'check_call'),
                ('zaza.charm_tests.lifecycle.refresh.model.get_application',
                 'get_application')]:
            patcher = patch(target)
            setattr(self, attribute, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {
            'CHARMS_ARTIFACT_DIR': str(self.directory)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, charm=None):
        charm = charm or self.charm
        return ['juju', 'refresh', '--path', str(charm), charm.stem]

    def test_without_resources(self):
        self.assertTrue(self.helper.run())
        self.check_call.assert_called_once_with(self.command())

    def test_runner_passes_scoped_resources(self):
        other = self.directory / 'ceph-mon.charm'
        other.touch()
        resource = self.directory / 'empty snap=placeholder.snap'
        resource.touch()
        # Exercise the actual direct runner's list argument convention.
        run_direct_with_args(refresh.CharmRefreshAll, 'refresh', [
            'ceph-osd:epa-orchestrator={}'.format(resource),
            'ceph-osd:another-resource=7'])
        self.check_call.assert_has_calls([
            call(self.command() + [
                '--resource', 'epa-orchestrator={}'.format(resource),
                '--resource', 'another-resource=7']),
            call(self.command(other))], any_order=True)
        self.assertEqual(self.check_call.call_count, 2)

    def test_resources_for_absent_application_are_not_forwarded(self):
        self.assertTrue(self.helper.run(['other:snap=/tmp/other.snap']))
        self.check_call.assert_called_once_with(self.command())

    def test_invalid_resources_fail_before_any_refresh(self):
        for argument in ['snap=file', ':snap=file', 'app:=file',
                         'app:snap=', 'app:snap']:
            with self.subTest(argument=argument):
                with self.assertRaisesRegex(ValueError,
                                            'Expected application'):
                    self.helper.run([argument])
        self.check_call.assert_not_called()

    def test_duplicate_resource_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate resource'):
            self.helper.run(['ceph-osd:snap=a', 'ceph-osd:snap=b'])
        self.check_call.assert_not_called()

    def test_undeployed_charm_skipped(self):
        self.get_application.side_effect = KeyError('ceph-osd')
        self.assertTrue(self.helper.run(['ceph-osd:snap=1']))
        self.check_call.assert_not_called()

    def test_missing_artifact_directory_skipped(self):
        del os.environ['CHARMS_ARTIFACT_DIR']
        self.assertTrue(self.helper.run())
        self.check_call.assert_not_called()

    def test_empty_artifact_directory_skipped(self):
        self.charm.unlink()
        self.assertTrue(self.helper.run())
        self.check_call.assert_not_called()

    def test_refresh_failure_propagates(self):
        self.check_call.side_effect = subprocess.CalledProcessError(1, 'juju')
        with self.assertRaises(subprocess.CalledProcessError):
            self.helper.run(['ceph-osd:snap=1'])
