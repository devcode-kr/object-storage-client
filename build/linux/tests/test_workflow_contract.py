from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "linux-packages.yml"
EXPECTED_MATRIX = {
    ("debian:12", "debian-12", "deb"),
    ("ubuntu:22.04", "ubuntu-22-04", "deb"),
    ("ubuntu:24.04", "ubuntu-24-04", "deb"),
    ("fedora:44", "fedora-44", "rpm"),
    ("fedora:43", "fedora-43", "rpm"),
    ("rockylinux:9", "rockylinux-9", "rpm"),
    ("almalinux:9", "almalinux-9", "rpm"),
}
ACTION_SHA = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def load_workflow():
    """Load YAML when available without YAML 1.1 turning `on` into True."""
    try:
        import yaml
    except ImportError:
        return None

    class WorkflowLoader(yaml.SafeLoader):
        pass

    WorkflowLoader.yaml_implicit_resolvers = {
        key: [
            resolver
            for resolver in resolvers
            if resolver[0] != "tag:yaml.org,2002:bool"
        ]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return yaml.load(workflow_text(), Loader=WorkflowLoader)


class LinuxPackageWorkflowContractTests(unittest.TestCase):
    def test_workflow_exists_and_yaml_loads(self):
        self.assertTrue(WORKFLOW.is_file())
        loaded = load_workflow()
        if loaded is not None:
            self.assertIsInstance(loaded, dict)
            self.assertIn("on", loaded)
            self.assertIn("jobs", loaded)

    def test_triggers_and_call_inputs_are_stable(self):
        loaded = load_workflow()
        if loaded is None:
            text = workflow_text()
            for trigger in ("pull_request:", "workflow_dispatch:", "workflow_call:"):
                self.assertIn(trigger, text)
            self.assertRegex(text, r"(?m)^\s+version:\s*$")
            self.assertRegex(text, r"(?m)^\s+package_release:\s*$")
            self.assertIn("default: ''", text)
            self.assertIn("default: '1'", text)
            return

        triggers = loaded["on"]
        self.assertEqual(
            {"pull_request", "workflow_dispatch", "workflow_call"}, set(triggers)
        )
        inputs = triggers["workflow_call"]["inputs"]
        self.assertEqual(
            {"description": "Application version override", "required": "false", "type": "string", "default": ""},
            inputs["version"],
        )
        self.assertEqual("string", inputs["package_release"]["type"])
        self.assertEqual("false", inputs["package_release"]["required"])
        self.assertEqual("1", inputs["package_release"]["default"])

    def test_permissions_concurrency_and_timeouts_are_restrictive(self):
        loaded = load_workflow()
        if loaded is None:
            text = workflow_text()
            self.assertRegex(text, r"(?m)^permissions:\s*\n\s+contents: read$")
            self.assertIn("concurrency:", text)
            self.assertGreaterEqual(text.count("timeout-minutes:"), 2)
            return

        self.assertEqual({"contents": "read"}, loaded["permissions"])
        self.assertTrue(loaded["concurrency"]["cancel-in-progress"] in ("true", True))
        self.assertEqual({"build", "smoke"}, set(loaded["jobs"]))
        for job in loaded["jobs"].values():
            self.assertIn("timeout-minutes", job)
            if "permissions" in job:
                self.assertEqual({"contents": "read"}, job["permissions"])

    def test_build_contract_and_container_tooling_are_exact(self):
        text = workflow_text()
        self.assertIn("runs-on: ubuntu-latest", text)
        self.assertEqual(1, len(re.findall(r"\bdotnet publish\b", text)))
        self.assertIn("--runtime linux-x64", text)
        self.assertIn("--self-contained true", text)
        self.assertIn("--output artifacts/publish/linux-x64", text)
        self.assertIn("dotnet test ObjectStorageClient.sln --configuration Release", text)
        self.assertIn("python3 -m unittest discover -s build/linux/tests", text)
        self.assertRegex(text, r"(?s)docker run --rm .*?debian:12 .*?package_deb\.py")
        self.assertRegex(text, r"(?s)docker run --rm .*?fedora:44 .*?package_rpm\.py")
        self.assertIn("build/linux/package_deb.py", text)
        self.assertIn("build/linux/package_rpm.py", text)
        for tool in ("apt-utils", "rpm", "rpmsign", "createrepo-c", "gnupg"):
            self.assertIn(tool, text)
        self.assertRegex(text, r"(?m)^\s+if \[\[ ! \"\$package_release\" =~ \^\[0-9\]\+\$ \]\]")
        self.assertIn("package_release > 65535", text)
        self.assertIn("NativeVersion.parse", text)

    def test_throwaway_signing_repository_and_artifacts_are_present(self):
        text = workflow_text()
        self.assertIn("Object Storage Client CI <ci@example.invalid>", text)
        self.assertRegex(text, r"--quick-generate-key .* rsa2048 sign 1d")
        self.assertIn("mktemp -d", text)
        self.assertIn("GNUPGHOME", text)
        self.assertIn("--export-secret-keys", text)
        self.assertIn("--expected-fingerprint", text)
        self.assertIn("build/linux/repository.py", text)
        self.assertIn("artifacts/linux-native", text)
        self.assertIn("artifacts/linux-smoke-packages", text)
        self.assertIn("artifacts/site", text)
        self.assertIn("artifacts/logs", text)
        self.assertIn("name: linux-package-validation", text)
        self.assertIn("retention-days:", text)

    def test_smoke_matrix_and_isolated_repository_server_are_exact(self):
        loaded = load_workflow()
        if loaded is None:
            text = workflow_text()
            entries = re.findall(
                r"(?m)^\s+- image: (\S+)\n\s+slug: (\S+)\n\s+kind: (\S+)",
                text,
            )
            self.assertEqual(EXPECTED_MATRIX, set(entries))
            self.assertEqual(len(EXPECTED_MATRIX), len(entries))
        else:
            include = loaded["jobs"]["smoke"]["strategy"]["matrix"]["include"]
            actual = {(entry["image"], entry["slug"], entry["kind"]) for entry in include}
            self.assertEqual(EXPECTED_MATRIX, actual)
            self.assertTrue(all(entry.get("package") for entry in include))

        text = workflow_text()
        self.assertIn("needs: build", text)
        self.assertIn("docker network create", text)
        self.assertIn("python:3-alpine", text)
        self.assertIn("--network-alias repository", text)
        self.assertIn("python3 -m http.server 8000", text)
        self.assertIn("REPOSITORY_URL=http://repository:8000", text)
        self.assertIn("build/linux/smoke-package.sh", text)
        self.assertIn('"/repository"', text)
        self.assertRegex(text, r"(?s)(?:while|for) .*repository:8000.*sleep")
        self.assertIn("if: always()", text)
        self.assertIn("docker network rm", text)

    def test_all_actions_are_immutable(self):
        uses = re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", workflow_text())
        self.assertTrue(uses)
        for action in uses:
            with self.subTest(action=action):
                self.assertRegex(action, ACTION_SHA)

    def test_forbidden_deployment_and_verification_bypasses_are_absent(self):
        lowered = workflow_text().lower()
        forbidden = (
            "linux_repo_gpg_",
            "trusted=yes",
            "--nogpgcheck",
            "setenforce",
            "printenv",
            "export -p",
            "gh-pages",
            "gh release",
            "create release",
            "deployment",
            "pages: write",
            "id-token: write",
            "contents: write",
        )
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, lowered)

    def test_multiline_shell_steps_enable_strict_mode_and_do_not_echo_secrets(self):
        text = workflow_text()
        snippets = re.findall(
            r"(?ms)^\s+run:\s*\|[-+]?\s*\n(?P<body>(?:\s{10,}.*(?:\n|$))*)", text
        )
        self.assertTrue(snippets)
        for snippet in snippets:
            with self.subTest(snippet=snippet[:80]):
                lines = [line.strip() for line in snippet.splitlines() if line.strip()]
                self.assertTrue(lines and lines[0] == "set -euo pipefail")
                self.assertNotRegex(snippet, r"(?m)^\s*(?:echo|printf)\s+\$(?:passphrase|private)")

    def test_publication_workflow_is_intentionally_out_of_scope_for_task_6a(self):
        # Task 6B will add publication/release integration contract tests. This
        # initial contract deliberately validates only linux-packages.yml.
        self.assertEqual("linux-packages.yml", WORKFLOW.name)


if __name__ == "__main__":
    unittest.main()
