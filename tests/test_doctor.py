from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from ai_story.cli import main
from ai_story.doctor import environment_report


class DoctorTests(unittest.TestCase):
    @patch("ai_story.cli.environment_report", return_value={"status": "NOT_READY"})
    def test_doctor_command_returns_failure_when_environment_is_not_ready(
        self, _environment_report
    ) -> None:
        with redirect_stdout(StringIO()):
            exit_code = main(["doctor"])
        self.assertEqual(exit_code, 1)

    @patch("ai_story.doctor.ProviderRuntimeRegistry")
    @patch("ai_story.doctor.importlib.util.find_spec")
    @patch("ai_story.doctor.shutil.which", return_value=None)
    def test_deterministic_mode_only_requires_core_dependencies(
        self, _which, find_spec, registry_type
    ) -> None:
        find_spec.side_effect = lambda name: object() if name == "PIL" else None
        registry_type.return_value.status.return_value = {"mode": "deterministic"}
        with patch(
            "ai_story.doctor.load_provider_config",
            return_value={
                "active_mode": "deterministic",
                "config_path": "providers.json",
            },
        ):
            report = environment_report()
        self.assertEqual(report["status"], "DEGRADED")
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(checks["CORE_DEPENDENCIES"]["status"], "PASS")
        self.assertEqual(checks["LOCAL_IMAGE_DEPENDENCIES"]["status"], "NOT_REQUIRED")
        self.assertEqual(checks["LOCAL_TEXT_RUNTIME"]["status"], "NOT_REQUIRED")

    @patch("ai_story.doctor.ProviderRuntimeRegistry")
    @patch("ai_story.doctor.importlib.util.find_spec", return_value=None)
    @patch("ai_story.doctor.shutil.which", return_value=None)
    def test_missing_core_dependency_makes_environment_not_ready(
        self, _which, _find_spec, registry_type
    ) -> None:
        registry_type.return_value.status.return_value = {"mode": "deterministic"}
        with patch(
            "ai_story.doctor.load_provider_config",
            return_value={
                "active_mode": "deterministic",
                "config_path": "providers.json",
            },
        ):
            report = environment_report()
        self.assertEqual(report["status"], "NOT_READY")
        self.assertIn("CORE_DEPENDENCIES", report["required_failures"])

    @patch("ai_story.doctor.ProviderRuntimeRegistry")
    @patch("ai_story.doctor.importlib.util.find_spec")
    @patch("ai_story.doctor.shutil.which", return_value=None)
    def test_local_mode_requires_text_and_image_stack(
        self, _which, find_spec, registry_type
    ) -> None:
        find_spec.side_effect = lambda name: object() if name == "PIL" else None
        registry_type.return_value.status.return_value = {"mode": "local"}
        with patch(
            "ai_story.doctor.load_provider_config",
            return_value={"active_mode": "local", "config_path": "providers.json"},
        ):
            report = environment_report()
        self.assertEqual(report["status"], "NOT_READY")
        self.assertIn("LOCAL_TEXT_RUNTIME", report["required_failures"])
        self.assertIn("LOCAL_IMAGE_DEPENDENCIES", report["required_failures"])


if __name__ == "__main__":
    unittest.main()
