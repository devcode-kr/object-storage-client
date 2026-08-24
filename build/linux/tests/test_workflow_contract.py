from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "linux-packages.yml"
PUBLICATION_WORKFLOW = ROOT / ".github" / "workflows" / "publish-linux-repositories.yml"
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


def workflow_text(path: pathlib.Path = WORKFLOW) -> str:
    return path.read_text(encoding="utf-8")


def load_workflow(path: pathlib.Path = WORKFLOW):
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
    return yaml.load(workflow_text(path), Loader=WorkflowLoader)


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
        dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs, dispatch_inputs)

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
        self.assertIn("artifacts/logs/linux-contract-tests.log", text)
        self.assertRegex(
            text,
            r"python3 -m unittest discover -s build/linux/tests[^\n]*\| tee artifacts/logs/linux-contract-tests\.log",
        )
        self.assertRegex(
            text,
            r"(?s)name: Upload failed test logs.*?if: failure\(\).*?name: linux-test-failure-logs.*?artifacts/logs/managed-tests\.log.*?artifacts/logs/linux-contract-tests\.log",
        )
        self.assertRegex(text, r"(?s)docker run --rm .*?debian:12 .*?package_deb\.py")
        self.assertRegex(text, r"(?s)docker run --rm .*?fedora:44 .*?package_rpm\.py")
        self.assertIn("build/linux/package_deb.py", text)
        self.assertIn("build/linux/package_rpm.py", text)
        for tool in ("apt-utils", "rpm", "rpmsign", "createrepo-c", "gnupg"):
            self.assertIn(tool, text)
        self.assertRegex(text, r"(?m)^\s+if \[\[ ! \"\$package_release\" =~ \^\[0-9\]\+\$ \]\]")
        self.assertIn("NativeVersion.parse", text)
        self.assertIn("print(native.package_release)", text)
        self.assertNotIn("10#$package_release", text)

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
        self.assertRegex(
            text,
            r'(?s)name: Clean up isolated smoke resources.*?docker logs "\$server".*?docker rm -f',
        )
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


class LinuxPublicationWorkflowContractTests(unittest.TestCase):
    def text(self) -> str:
        return workflow_text(PUBLICATION_WORKFLOW)

    def test_publication_workflow_exists_and_has_exact_call_interface(self):
        self.assertTrue(PUBLICATION_WORKFLOW.is_file())
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        self.assertIsInstance(loaded, dict)
        self.assertEqual({"workflow_call"}, set(loaded["on"]))
        call = loaded["on"]["workflow_call"]
        inputs = call["inputs"]
        self.assertEqual(
            {"mode", "version", "package_release", "validation_artifact", "candidate_artifact"},
            set(inputs),
        )
        for name in ("mode", "version", "package_release"):
            self.assertEqual("string", inputs[name]["type"])
            self.assertEqual("true", inputs[name]["required"])
        self.assertEqual("linux-package-validation", inputs["validation_artifact"]["default"])
        self.assertEqual("linux-pages-candidate", inputs["candidate_artifact"]["default"])
        self.assertEqual(
            {"LINUX_REPO_GPG_PRIVATE_KEY", "LINUX_REPO_GPG_PASSPHRASE"},
            set(call["secrets"]),
        )
        self.assertTrue(all(value["required"] == "true" for value in call["secrets"].values()))

    def test_job_guards_permissions_timeouts_and_concurrency_are_restrictive(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        self.assertEqual({"contents": "read"}, loaded["permissions"])
        self.assertIn("concurrency", loaded)
        self.assertEqual({"prepare", "publish"}, set(loaded["jobs"]))
        self.assertEqual({"contents": "read"}, loaded["jobs"]["prepare"]["permissions"])
        self.assertEqual(
            {"contents": "write", "pages": "write"}, loaded["jobs"]["publish"]["permissions"]
        )
        for mode, job in loaded["jobs"].items():
            guard = job["if"]
            self.assertIn("github.ref_type == 'tag'", guard)
            self.assertIn("startsWith(github.ref, 'refs/tags/v')", guard)
            self.assertIn(f"inputs.mode == '{mode}'", guard)
            self.assertIn("timeout-minutes", job)

    def test_prepare_retains_pages_and_builds_release_and_candidate_artifacts(self):
        text = self.text()
        for marker in (
            "NativeVersion.parse", 'refs/tags/v${VERSION}', "git fetch origin gh-pages",
            "git archive origin/gh-pages | tar -x -C candidate/site", "build/linux/repository.py",
            "--base-url https://devcode-kr.github.io/object-storage-client",
            "candidate/release-packages", "SHA256SUMS", "name: linux-release-packages",
            "name: ${{ inputs.candidate_artifact }}", "artifacts/linux-native",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("rm -rf candidate/site/apt", text)
        self.assertNotIn("rm -rf candidate/site/rpm", text)

    def test_publish_preserves_history_and_outputs_the_exact_commit(self):
        text = self.text()
        for marker in (
            "git worktree add", "origin/gh-pages", "git checkout --orphan gh-pages",
            'Publish Linux packages ${VERSION}-${PACKAGE_RELEASE}', "git push origin HEAD:gh-pages",
            "id: publish", 'commit=$(git -C pages rev-parse HEAD)',
            "printf 'commit=%s\\n' \"$commit\"", 'GITHUB_OUTPUT',
        ):
            self.assertIn(marker, text)
        self.assertNotRegex(text, r"git push[^\n]*(?:--force|-f\b)")

    def test_pages_must_be_preconfigured_and_the_exact_build_is_polled(self):
        text = self.text()
        self.assertNotRegex(text, r"gh api\s+--method\s+(?:POST|PUT)[^\n]*pages")
        self.assertNotIn("-f build_type=legacy", text)
        self.assertIn('gh api "repos/${REPOSITORY}/pages"', text)
        self.assertIn("one-time preconfiguration required", text)
        for marker in (
            "build_type", "legacy", "source", "gh-pages", "PUBLIC_BASE_URL",
            'steps.publish.outputs.commit', 'repos/${REPOSITORY}/pages/builds/latest',
            "status", "built", "commit", "seq 1 60", "sleep 10",
        ):
            self.assertIn(marker, text)
        self.assertRegex(text, r"(?s)builds/latest.*?(?:errored|error).*?exit 1")

    def test_public_readiness_and_fetches_are_strictly_bounded(self):
        text = self.text()
        self.assertIn('candidate_key_hash="$(sha256sum candidate/site/repository-key.asc', text)
        self.assertIn("readiness_deadline=$((SECONDS +", text)
        self.assertIn("public_key_hash", text)
        for marker in (
            "--connect-timeout 5", "--max-time 20", "--retry 3",
            "--retry-all-errors", "--retry-max-time", "--fail", "404",
        ):
            self.assertIn(marker, text)
        fetch = re.search(r"fetch\(\)\s*\{(?P<body>.*?)\n\s*\}", text, re.DOTALL)
        self.assertIsNotNone(fetch)
        assert fetch is not None
        for marker in ("--connect-timeout", "--max-time", "--retry", "--retry-all-errors", "--retry-max-time"):
            self.assertIn(marker, fetch.group("body"))

    def test_complete_apt_readback_uses_safe_manifest_and_every_indexed_deb(self):
        text = self.text()
        for marker in (
            "fetch apt/dists/stable/main/binary-amd64/Packages ",
            "apt/dists/stable/main/binary-amd64/Packages.gz",
            "gzip.decompress", "apt-packages-manifest.tsv", "Filename",
            "PurePosixPath", "pool", "Package", "object-storage-client",
            "Architecture", "amd64", "Version", "Size", "SHA256",
            "current_apt_found", "while IFS=$'\\t' read -r relative size sha256",
            'fetch "$relative"', 'candidate/site/$relative',
        ):
            self.assertIn(marker, text)

    def test_complete_rpm_readback_validates_all_metadata_and_packages(self):
        text = self.text()
        for marker in (
            "repodata-manifest.tsv", "primary", "filelists", "other",
            "checksum", "location", "repodata", "rpm-packages-manifest.tsv",
            "gzip.decompress", "object-storage-client", "x86_64",
            "rpm/stable/x86_64", "current_rpm_found",
            "while IFS=$'\\t' read -r kind relative algorithm expected",
            "while IFS=$'\\t' read -r relative size algorithm expected",
            'fetch "$relative"', 'candidate/site/$relative',
            'rpm --dbpath "$rpm_root/rpmdb" --initdb',
            'rpm --dbpath "$rpm_root/rpmdb" --import',
            'rpm --dbpath "$rpm_root/rpmdb" --checksig',
            ": digests signatures OK$",
        ):
            self.assertIn(marker, text)
        self.assertNotIn('rpm --root "$rpm_root"', text)
        self.assertRegex(text, r'install -d -m 0700[^\n]*"\$rpm_root/rpmdb"')

    def test_public_signatures_are_verified(self):
        text = self.text()
        for marker in (
            "repository-key.asc", "InRelease", "Release.gpg", "repomd.xml.asc",
            "VALIDSIG", "EXPECTED_FINGERPRINT",
        ):
            self.assertIn(marker, text)

    def test_gpg_configuration_is_exact_and_secrets_are_not_printed_or_bypassed(self):
        text = self.text()
        for marker in (
            "secrets.LINUX_REPO_GPG_PRIVATE_KEY", "secrets.LINUX_REPO_GPG_PASSPHRASE",
            "vars.LINUX_REPO_GPG_FINGERPRINT", "build/linux/repository-key.asc",
            "printf '%s' \"$PRIVATE_KEY\"", "printf '%s' \"$PASSPHRASE\"",
            "chmod 0600", "unset PRIVATE_KEY PASSPHRASE", "--pinentry-mode loopback",
        ):
            self.assertIn(marker, text)
        lowered = text.lower()
        for marker in ("trusted=yes", "--nogpgcheck", "printenv", "export -p", "cat $", "echo $"):
            self.assertNotIn(marker, lowered)

    def test_all_publication_actions_are_immutable(self):
        uses = re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", self.text())
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, ACTION_SHA)

    def test_multiline_publication_shell_is_strict_and_parses_as_bash(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        snippets = [
            step["run"]
            for job in loaded["jobs"].values()
            for step in job["steps"]
            if "run" in step
        ]
        self.assertTrue(snippets)
        for body in snippets:
            self.assertEqual("set -euo pipefail", next(line for line in body.splitlines() if line.strip()))
            with tempfile.NamedTemporaryFile("w", suffix=".bash", encoding="utf-8") as script:
                script.write(body)
                script.flush()
                result = subprocess.run(["bash", "-n", script.name], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_embedded_publication_python_parses(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        snippets = [
            match.group("body")
            for job in loaded["jobs"].values()
            for step in job["steps"]
            for match in re.finditer(
                r"<<'PY'\n(?P<body>.*?)\nPY(?:\n|$)", step.get("run", ""), re.DOTALL
            )
        ]
        self.assertTrue(snippets)
        for snippet in snippets:
            with self.subTest(snippet=snippet[:80]):
                compile(snippet, "<workflow-python>", "exec")

    def test_release_integration_is_deferred_to_task_6b2(self):
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertNotIn("publish-linux-repositories.yml", release)


if __name__ == "__main__":
    unittest.main()
