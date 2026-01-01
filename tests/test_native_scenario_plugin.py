#!/usr/bin/env python3

"""
Test suite for NativeScenarioPlugin class and Plugins/PluginStep classes

Usage:
    python -m coverage run -a -m unittest tests/test_native_scenario_plugin.py -v

Assisted By: Claude Code
"""

import unittest
import json
import tempfile
import os
from unittest.mock import MagicMock, Mock, patch

from krkn_lib.k8s import KrknKubernetes
from krkn_lib.telemetry.ocp import KrknTelemetryOpenshift
from arcaflow_plugin_sdk import schema

from krkn.scenario_plugins.native.native_scenario_plugin import NativeScenarioPlugin
from krkn.scenario_plugins.native.plugins import PluginStep, Plugins


class TestNativeScenarioPlugin(unittest.TestCase):

    def setUp(self):
        """
        Set up test fixtures for NativeScenarioPlugin
        """
        self.plugin = NativeScenarioPlugin()

    def test_get_scenario_types(self):
        """
        Test get_scenario_types returns correct scenario types
        """
        result = self.plugin.get_scenario_types()

        self.assertEqual(result, ["pod_network_scenarios", "ingress_node_scenarios"])
        self.assertEqual(len(result), 2)


class TestPluginStep(unittest.TestCase):
    """Test suite for PluginStep class"""

    def setUp(self):
        """Set up test fixtures"""
        # Create a mock schema
        self.mock_schema = Mock(spec=schema.StepSchema)
        self.mock_schema.id = "test-step"

        # Mock output schema
        mock_output = Mock()
        mock_output.serialize = Mock(return_value={"status": "success"})
        self.mock_schema.outputs = {"success": mock_output}

        self.plugin_step = PluginStep(
            schema=self.mock_schema,
            error_output_ids=["error"]
        )

    def test_plugin_step_init(self):
        """Test PluginStep initialization"""
        self.assertEqual(self.plugin_step.schema, self.mock_schema)
        self.assertEqual(self.plugin_step.error_output_ids, ["error"])

    def test_render_output(self):
        """Test render_output method"""
        output_id = "success"
        output_data = {"message": "Test completed"}

        result = self.plugin_step.render_output(output_id, output_data)

        # Verify it's valid JSON
        parsed = json.loads(result)
        self.assertEqual(parsed["output_id"], "success")
        self.assertEqual(parsed["output_data"], {"status": "success"})

        # Verify serialize was called
        self.mock_schema.outputs[output_id].serialize.assert_called_once_with(output_data)


class TestPlugins(unittest.TestCase):
    """Test suite for Plugins class"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mock steps
        self.mock_step1 = self._create_mock_step("step1")
        self.mock_step2 = self._create_mock_step("step2")

        self.plugin_steps = [
            PluginStep(self.mock_step1, ["error"]),
            PluginStep(self.mock_step2, ["error"])
        ]

    def _create_mock_step(self, step_id):
        """Helper to create a mock step schema"""
        mock_step = Mock(spec=schema.StepSchema)
        mock_step.id = step_id

        # Mock input
        mock_input = Mock()
        mock_input.properties = {}
        mock_input.unserialize = Mock(return_value=Mock())
        mock_step.input = mock_input

        # Mock outputs
        mock_output = Mock()
        mock_output.serialize = Mock(return_value={"status": "success"})
        mock_step.outputs = {"success": mock_output}

        # Mock schema call
        mock_step.return_value = ("success", {"result": "ok"})

        return mock_step

    def test_plugins_init(self):
        """Test Plugins initialization"""
        plugins = Plugins(self.plugin_steps)

        self.assertEqual(len(plugins.steps_by_id), 2)
        self.assertIn("step1", plugins.steps_by_id)
        self.assertIn("step2", plugins.steps_by_id)

    def test_plugins_init_duplicate_step_id(self):
        """Test Plugins initialization with duplicate step IDs"""
        duplicate_step = PluginStep(self.mock_step1, ["error"])

        with self.assertRaises(Exception) as context:
            Plugins([self.plugin_steps[0], duplicate_step])

        self.assertIn("Duplicate step ID", str(context.exception))

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    def test_unserialize_scenario(self, mock_load):
        """Test unserialize_scenario method"""
        plugins = Plugins(self.plugin_steps)
        mock_load.return_value = [{"id": "step1", "config": {}}]

        result = plugins.unserialize_scenario("/tmp/test.yaml")

        mock_load.assert_called_once()
        self.assertEqual(result, [{"id": "step1", "config": {}}])

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    @patch('logging.info')
    def test_run_valid_scenario(self, mock_logging, mock_load):
        """Test run method with valid scenario"""
        plugins = Plugins(self.plugin_steps)

        scenario_data = [
            {"id": "step1", "config": {"param": "value1"}},
            {"id": "step2", "config": {"param": "value2"}}
        ]
        mock_load.return_value = scenario_data

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid-123")

            # Verify both steps were executed
            self.mock_step1.assert_called_once()
            self.mock_step2.assert_called_once()

            # Verify logging was called
            self.assertTrue(mock_logging.called)
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    def test_run_invalid_scenario_not_list(self, mock_load):
        """Test run method with non-list scenario data"""
        plugins = Plugins(self.plugin_steps)
        mock_load.return_value = {"not": "a list"}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            with self.assertRaises(Exception) as context:
                plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            self.assertIn("expected list", str(context.exception))
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    def test_run_invalid_scenario_entry_not_dict(self, mock_load):
        """Test run method with non-dict entry in scenario"""
        plugins = Plugins(self.plugin_steps)
        mock_load.return_value = ["not a dict"]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            with self.assertRaises(Exception) as context:
                plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            self.assertIn("expected a list of dict's", str(context.exception))
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    def test_run_missing_id_field(self, mock_load):
        """Test run method with missing 'id' field"""
        plugins = Plugins(self.plugin_steps)
        mock_load.return_value = [{"config": {}}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            with self.assertRaises(Exception) as context:
                plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            self.assertIn("missing 'id' field", str(context.exception))
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    def test_run_missing_config_field(self, mock_load):
        """Test run method with missing 'config' field"""
        plugins = Plugins(self.plugin_steps)
        mock_load.return_value = [{"id": "step1"}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            with self.assertRaises(Exception) as context:
                plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            self.assertIn("missing 'config' field", str(context.exception))
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    def test_run_invalid_step_id(self, mock_load):
        """Test run method with invalid step ID"""
        plugins = Plugins(self.plugin_steps)
        mock_load.return_value = [{"id": "invalid-step", "config": {}}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            with self.assertRaises(Exception) as context:
                plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            self.assertIn("Invalid step", str(context.exception))
            self.assertIn("invalid-step", str(context.exception))
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    @patch('logging.info')
    def test_run_with_kubeconfig_path_in_properties(self, mock_logging, mock_load):
        """Test run method injects kubeconfig_path when in step properties"""
        mock_step = self._create_mock_step("step-with-kubeconfig")
        mock_step.input.properties = {"kubeconfig_path": True}

        plugins = Plugins([PluginStep(mock_step, ["error"])])
        mock_load.return_value = [{"id": "step-with-kubeconfig", "config": {}}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            # Verify kubeconfig_path was set
            unserialized_input = mock_step.input.unserialize.return_value
            self.assertEqual(unserialized_input.kubeconfig_path, "/path/to/kubeconfig")
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    @patch('logging.info')
    def test_run_with_kraken_config_in_properties(self, mock_logging, mock_load):
        """Test run method injects kraken_config when in step properties"""
        mock_step = self._create_mock_step("step-with-kraken-config")
        mock_step.input.properties = {"kraken_config": True}

        plugins = Plugins([PluginStep(mock_step, ["error"])])
        mock_load.return_value = [{"id": "step-with-kraken-config", "config": {}}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            # Verify kraken_config was set
            unserialized_input = mock_step.input.unserialize.return_value
            self.assertEqual(unserialized_input.kraken_config, "/path/to/kraken")
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.serialization.load_from_file')
    @patch('logging.info')
    def test_run_step_failure(self, mock_logging, mock_load):
        """Test run method when step returns error output"""
        mock_step = self._create_mock_step("failing-step")

        # Add error output to the mock schema outputs
        mock_error_output = Mock()
        mock_error_output.serialize = Mock(return_value={"error": "Step failed"})
        mock_step.outputs["error"] = mock_error_output

        # Make the step return an error output
        mock_step.return_value = ("error", {"message": "Step failed"})

        plugins = Plugins([PluginStep(mock_step, ["error"])])
        mock_load.return_value = [{"id": "failing-step", "config": {}}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            temp_file = f.name

        try:
            with self.assertRaises(Exception) as context:
                plugins.run(temp_file, "/path/to/kubeconfig", "/path/to/kraken", "run-uuid")

            # Exception message format: "Step 0 in {file} (failing-step) failed"
            exception_str = str(context.exception)
            self.assertIn("Step", exception_str)
            self.assertIn("failed", exception_str)
            self.assertIn("failing-step", exception_str)
        finally:
            os.unlink(temp_file)

    @patch('krkn.scenario_plugins.native.plugins.jsonschema.step_input')
    def test_json_schema(self, mock_step_input):
        """Test json_schema method generates valid schema"""
        plugins = Plugins(self.plugin_steps)

        # Mock the step_input return value - it needs to be a mutable dict
        # that can have keys deleted from it
        def create_mock_schema():
            return {
                "$id": "test-id",
                "$schema": "test-schema",
                "title": "Test Title",
                "description": "Test Description",
                "type": "object",
                "properties": {}
            }

        mock_step_input.side_effect = [create_mock_schema(), create_mock_schema()]

        result = plugins.json_schema()

        # Verify it's valid JSON
        schema_obj = json.loads(result)

        self.assertEqual(schema_obj["$id"], "https://github.com/redhat-chaos/krkn/")
        self.assertEqual(schema_obj["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema_obj["title"], "Kraken Arcaflow scenarios")
        self.assertEqual(schema_obj["type"], "array")
        self.assertIn("oneOf", schema_obj["items"])

        # Verify both steps are in the schema
        self.assertEqual(len(schema_obj["items"]["oneOf"]), 2)

        # Verify step structure
        step_schema = schema_obj["items"]["oneOf"][0]
        self.assertEqual(step_schema["type"], "object")
        self.assertIn("id", step_schema["properties"])
        self.assertIn("config", step_schema["properties"])
        self.assertIn("id", step_schema["required"])
        self.assertIn("config", step_schema["required"])

        # Verify the config has the expected properties
        config_schema = step_schema["properties"]["config"]
        self.assertEqual(config_schema["type"], "object")
        self.assertNotIn("$id", config_schema)
        self.assertNotIn("$schema", config_schema)
        self.assertNotIn("title", config_schema)
        self.assertNotIn("description", config_schema)


if __name__ == "__main__":
    unittest.main()
