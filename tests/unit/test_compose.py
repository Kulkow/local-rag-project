"""Validate resolved packaging without pulling images or using the Docker daemon."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("docker"), "Docker CLI required to parse Compose")
class ComposePackagingTests(unittest.TestCase):
    def test_minio_build_preserves_storage_and_health_dependency(self) -> None:
        environment = dict(os.environ)
        environment.update(
            {
                "POSTGRES_PASSWORD": "configuration-test-only",
                "JWT_SECRET": "configuration-test-only-signing-key",
                "MINIO_ROOT_USER": "configuration-test-only",
                "MINIO_ROOT_PASSWORD": "configuration-test-only",
                "ADMIN_USERNAME": "configuration-test-only",
                "ADMIN_PASSWORD": "configuration-test-only",
            }
        )
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        services = json.loads(result.stdout)["services"]
        minio = services["minio"]
        self.assertEqual(minio["image"], "enterprise-rag-minio:local")
        self.assertEqual(Path(minio["build"]["context"]), ROOT / "infra/minio")
        self.assertTrue(any(volume["source"] == "minio-data" for volume in minio["volumes"]))
        self.assertIn("/minio/health/ready", minio["healthcheck"]["test"][-1])
        self.assertEqual(services["api"]["depends_on"]["minio"]["condition"], "service_healthy")

    def test_single_consumer_and_private_monitoring(self) -> None:
        environment = dict(os.environ)
        environment.update(
            {
                "POSTGRES_PASSWORD": "configuration-test-only",
                "JWT_SECRET": "configuration-test-only-signing-key",
                "MINIO_ROOT_USER": "configuration-test-only",
                "MINIO_ROOT_PASSWORD": "configuration-test-only",
                "ADMIN_USERNAME": "configuration-test-only",
                "ADMIN_PASSWORD": "configuration-test-only",
            }
        )
        result = subprocess.run(
            ["docker", "compose", "--profile", "monitoring", "config", "--format", "json"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        services = json.loads(result.stdout)["services"]
        worker_command = services["worker"]["command"]
        self.assertIn("--concurrency=1", worker_command)
        self.assertIn("--beat", worker_command)
        self.assertFalse(services["prometheus"].get("ports"))
        self.assertFalse(services["queue-metrics"].get("ports"))
        grafana_port = services["grafana"]["ports"][0]
        self.assertEqual(grafana_port["host_ip"], "127.0.0.1")
        self.assertEqual(str(grafana_port["published"]), "3001")
        self.assertEqual(services["grafana"]["environment"]["GF_AUTH_ANONYMOUS_ENABLED"], "false")
