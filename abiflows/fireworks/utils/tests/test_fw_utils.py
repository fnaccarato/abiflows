# coding: utf-8
from __future__ import unicode_literals, division, print_function

import os
import shutil
import unittest
from abiflows.core.testing import AbiflowsTest, has_mongodb
from abiflows.fireworks.utils.fw_utils import *
from abiflows.fireworks.workflows.abinit_workflows import AbstractFWWorkflow
from monty.tempfile import ScratchDir
from fireworks import Firework
from fireworks.core.rocket_launcher import rapidfire
from fireworks.user_objects.firetasks.script_task import PyTask

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

test_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                        "test_files", "fw_task_managers")



class TestFWTaskManager(AbiflowsTest):

    def test_ok(self):

        ftm = FWTaskManager.from_file(os.path.join(test_dir, "fw_manager_ok.yaml"))
        ftm.update_fw_policy({'max_restarts': 30})

        self.assertTrue(ftm.fw_policy.rerun_same_dir)
        self.assertEqual(ftm.fw_policy.max_restarts, 30)
        self.assertTrue(ftm.fw_policy.autoparal)

    def test_no_qadapter(self):

        ftm = FWTaskManager.from_file(os.path.join(test_dir, "fw_manager_no_qadapters.yaml"))

        self.assertIsNone(ftm.task_manager)

    def test_unknown_keys(self):

        with self.assertRaises(RuntimeError):
            ftm = FWTaskManager.from_file(os.path.join(test_dir, "fw_manager_unknown_keys.yaml"))

    def test_from_user_config(self):

        # create also using the from_user_config classmethod. Copy the file in the current folder
        with ScratchDir("."):
            shutil.copy2(os.path.join(test_dir, "fw_manager_ok.yaml"),
                         os.path.join(os.getcwd(), FWTaskManager.YAML_FILE))
            ftm = FWTaskManager.from_user_config()
            ftm.update_fw_policy({'max_restarts': 30})

            self.assertTrue(ftm.fw_policy.rerun_same_dir)
            self.assertEqual(ftm.fw_policy.max_restarts, 30)
            self.assertTrue(ftm.fw_policy.autoparal)


class TestFunctions(AbiflowsTest):

    @classmethod
    def setUpClass(cls):
        cls.setup_fireworks()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_fireworks(module_dir=MODULE_DIR)

    def test_get_short_single_core_spec(self):
        ftm_path = os.path.join(test_dir, "fw_manager_ok.yaml")
        ftm = FWTaskManager.from_file(ftm_path)
        spec = get_short_single_core_spec(ftm)
        assert spec['ntasks'] == 1

        spec = get_short_single_core_spec(ftm_path, timelimit=610)
        assert spec['ntasks'] == 1
        assert spec['time'] == '0-0:10:10'

    def test_set_short_single_core_to_spec(self):
        ftm_path = os.path.join(test_dir, "fw_manager_ok.yaml")
        spec = {}
        spec = set_short_single_core_to_spec(spec, fw_manager=ftm_path)

        assert spec['_queueadapter']['ntasks'] == 1
        assert spec['mpi_ncpus'] == 1

    @unittest.skipUnless(has_mongodb(), "A local mongodb is required.")
    def test_get_time_report_for_wf(self):
        task = PyTask(func="time.sleep", args=[0.5])
        fw1 = Firework([task], spec={'wf_task_index': "test1_1", "nproc": 16}, fw_id=1)
        fw2 = Firework([task], spec={'wf_task_index': "test2_1", "nproc": 16}, fw_id=2)
        wf = Workflow([fw1,fw2])
        self.lp.add_wf(wf)

        rapidfire(self.lp, self.fworker, m_dir=MODULE_DIR)

        wf = self.lp.get_wf_by_fw_id(1)

        assert wf.state == "COMPLETED"

        tr = get_time_report_for_wf(wf)

        assert tr.n_fws == 2
        assert tr.total_run_time > 1
