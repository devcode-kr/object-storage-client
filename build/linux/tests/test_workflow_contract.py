from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "linux-packages.yml"
PUBLICATION_WORKFLOW = ROOT / ".github" / "workflows" / "publish-linux-repositories.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
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
        self.assertEqual({"prepare", "publish"}, set(loaded["jobs"]))
        self.assertEqual({"contents": "read"}, loaded["jobs"]["prepare"]["permissions"])
        self.assertEqual(
            {"contents": "write", "pages": "write", "id-token": "write"},
            loaded["jobs"]["publish"]["permissions"],
        )
        self.assertEqual("github-pages", loaded["jobs"]["publish"]["environment"]["name"])
        self.assertEqual(
            "${{ steps.deployment.outputs.page_url }}",
            loaded["jobs"]["publish"]["environment"]["url"],
        )
        self.assertEqual("false", loaded["jobs"]["publish"]["concurrency"]["cancel-in-progress"])
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
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        upload = next(
            step for step in loaded["jobs"]["prepare"]["steps"]
            if step.get("with", {}).get("name") == "${{ inputs.candidate_artifact }}"
        )
        self.assertEqual("true", upload["with"]["include-hidden-files"])

    def test_publish_regenerates_latest_history_then_deploys_official_pages_artifact(self):
        text = self.text()
        for marker in (
            "git worktree add", "origin/gh-pages", "git checkout --orphan gh-pages",
            'Publish Linux packages ${VERSION}-${PACKAGE_RELEASE}', "git push origin HEAD:gh-pages",
            "path: deployment/site", "id: deployment", "steps.deployment.outputs.page_url",
            "name: linux-release-packages", "path: prepared/release-packages",
            "name: ${{ inputs.validation_artifact }}", "path: artifacts",
            "git archive origin/gh-pages | tar -x -C deployment/site",
            "build/linux/repository.py", "artifacts/linux-native", "cmp -s --",
            "deployment/site/.nojekyll",
        ):
            self.assertIn(marker, text)
        self.assertIn("actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa", text)
        self.assertIn("actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e", text)
        self.assertNotRegex(text, r"git push[^\n]*(?:--force|-f\b)")
        self.assertNotIn("rsync -a --delete --exclude .git candidate/site/", text)

        loaded = load_workflow(PUBLICATION_WORKFLOW)
        names = [step["name"] for step in loaded["jobs"]["publish"]["steps"]]
        history = names.index("Regenerate from latest gh-pages and publish package history")
        upload = names.index("Upload Pages artifact")
        deploy = names.index("Deploy Pages artifact")
        readback = names.index("Read back and cryptographically verify every public repository object")
        self.assertLess(history, upload)
        self.assertLess(upload, deploy)
        self.assertLess(deploy, readback)

    def test_pages_preconfiguration_is_get_only_and_precedes_publication(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        steps = loaded["jobs"]["publish"]["steps"]
        names = [step["name"] for step in steps]
        verify_index = names.index("Verify Pages is preconfigured")
        publish_index = names.index("Regenerate from latest gh-pages and publish package history")
        self.assertLess(verify_index, publish_index)

        verify = steps[verify_index]["run"]
        self.assertIn('gh api "repos/${REPOSITORY}/pages"', verify)
        self.assertIn("one-time preconfiguration required", verify)
        for marker in ("build_type", "workflow", "PUBLIC_BASE_URL", "html_url"):
            self.assertIn(marker, verify)
        for legacy in ("legacy", "source", "gh-pages"):
            self.assertNotIn(legacy, verify)
        self.assertGreaterEqual(verify.count(".rstrip('/')"), 2)
        self.assertNotRegex(verify, r"gh api\s+--method\s+(?:POST|PUT|PATCH|DELETE)")
        self.assertNotIn("-f build_type=", verify)

        later = "\n".join(step.get("run", "") for step in steps[verify_index + 1 :])
        self.assertEqual(1, self.text().count('gh api "repos/${REPOSITORY}/pages"'))
        self.assertNotIn("one-time preconfiguration required", later)
        self.assertNotRegex(later, r"gh api\s+--method\s+(?:POST|PUT|PATCH|DELETE)[^\n]*pages")

    def test_deploy_output_url_is_normalized_and_legacy_build_polling_is_absent(self):
        text = self.text()
        self.assertNotIn("builds/latest", text)
        self.assertNotIn("Wait for the exact published Pages build", text)
        self.assertIn("DEPLOYED_PAGE_URL: ${{ steps.deployment.outputs.page_url }}", text)
        self.assertIn("actual = sys.argv[1].rstrip('/')", text)
        self.assertIn("expected = sys.argv[2].rstrip('/')", text)

    def test_public_readiness_requires_coherent_apt_and_rpm_metadata_and_is_bounded(self):
        text = self.text()
        for marker in (
            'deployment_inrelease_hash="$(sha256sum deployment/site/apt/dists/stable/InRelease',
            'deployment_repomd_hash="$(sha256sum deployment/site/rpm/stable/x86_64/repodata/repomd.xml',
            "readiness_deadline=$((SECONDS +", "public_inrelease_hash", "public_repomd_hash",
            'readiness-InRelease', 'readiness-repomd.xml',
            "--connect-timeout 5", "--max-time 20", "--retry 3",
            "--retry-all-errors", "--retry-max-time", "--fail", "404",
        ):
            self.assertIn(marker, text)
        coherence = re.search(
            r'if \[\[ "\$public_inrelease_hash" == "\$deployment_inrelease_hash" '
            r'&& "\$public_repomd_hash" == "\$deployment_repomd_hash" \]\]; then',
            text,
        )
        self.assertIsNotNone(coherence)
        readiness = re.search(
            r"readiness_deadline=.*?(?=\n\s+fetch apt/dists/stable/Release )", text, re.DOTALL
        )
        self.assertIsNotNone(readiness)
        assert readiness is not None
        self.assertNotIn("deployment_key_hash", readiness.group())
        self.assertNotIn("public_key_hash", readiness.group())
        self.assertNotRegex(readiness.group(), r'if \[\[ "\$public_key_hash" == "\$candidate_key_hash" \]\]; then\s+break')
        self.assertIn('rm -f -- "$verify_root/readiness-InRelease" "$verify_root/readiness-repomd.xml"', readiness.group())
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
            'fetch "$relative"', 'deployment/site/$relative',
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
            'fetch "$relative"', 'deployment/site/$relative',
            'rpm --dbpath "$rpm_root/rpmdb" --initdb',
            'rpm --dbpath "$rpm_root/rpmdb" --import',
            'rpm --dbpath "$rpm_root/rpmdb" --checksig',
            ": digests signatures OK$",
        ):
            self.assertIn(marker, text)
        self.assertNotIn('rpm --root "$rpm_root"', text)
        self.assertRegex(text, r'install -d -m 0700[^\n]*"\$rpm_root/rpmdb"')

    def test_public_signatures_are_verified_with_primary_fingerprint_parser(self):
        text = self.text()
        for marker in (
            "repository-key.asc", "InRelease", "Release.gpg", "repomd.xml.asc",
            "VALIDSIG", "EXPECTED_FINGERPRINT", "_validsig_primary_fingerprints",
        ):
            self.assertIn(marker, text)
        repository = (ROOT / "build/linux/repository.py").read_text(encoding="utf-8")
        self.assertIn("fields[11]", repository)
        self.assertNotRegex(text, r"gpg[^\n]*--verify[^\n]*(?:\n[^\n]*)?\|\s*grep[^\n]*VALIDSIG")

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


class ReleaseWorkflowIntegrationContractTests(unittest.TestCase):
    def setUp(self):
        loaded = load_workflow(RELEASE_WORKFLOW)
        self.assertIsInstance(loaded, dict)
        assert loaded is not None
        self.loaded = loaded
        self.text = workflow_text(RELEASE_WORKFLOW)

    def test_release_yaml_triggers_and_job_interface_are_exact(self):
        self.assertEqual({"push", "workflow_dispatch"}, set(self.loaded["on"]))
        self.assertEqual(["v*"], self.loaded["on"]["push"]["tags"])
        self.assertEqual({}, self.loaded["on"]["workflow_dispatch"] or {})
        self.assertEqual(
            {
                "verify", "test", "package", "linux_packages",
                "prepare_linux_repositories", "release", "publish_linux_repositories",
            },
            set(self.loaded["jobs"]),
        )

        linux = self.loaded["jobs"]["linux_packages"]
        self.assertEqual("verify", linux["needs"])
        self.assertEqual("./.github/workflows/linux-packages.yml", linux["uses"])
        self.assertEqual(
            {"version": "${{ needs.verify.outputs.version }}", "package_release": "1"},
            linux["with"],
        )
        self.assertNotIn("if", linux)

        expected_secrets = {
            "LINUX_REPO_GPG_PRIVATE_KEY": "${{ secrets.LINUX_REPO_GPG_PRIVATE_KEY }}",
            "LINUX_REPO_GPG_PASSPHRASE": "${{ secrets.LINUX_REPO_GPG_PASSPHRASE }}",
        }
        for name, mode in (("prepare_linux_repositories", "prepare"), ("publish_linux_repositories", "publish")):
            job = self.loaded["jobs"][name]
            self.assertEqual("./.github/workflows/publish-linux-repositories.yml", job["uses"])
            self.assertEqual(
                {
                    "mode": mode,
                    "version": "${{ needs.verify.outputs.version }}",
                    "package_release": "1",
                    "validation_artifact": "linux-package-validation",
                    "candidate_artifact": "linux-pages-candidate",
                },
                job["with"],
            )
            self.assertEqual(expected_secrets, job["secrets"])

    def test_dependency_order_tag_guards_and_manual_safety_are_exact(self):
        jobs = self.loaded["jobs"]
        self.assertEqual({"verify", "linux_packages"}, set(jobs["prepare_linux_repositories"]["needs"]))
        self.assertEqual(
            {"verify", "package", "linux_packages", "prepare_linux_repositories"},
            set(jobs["release"]["needs"]),
        )
        self.assertEqual(
            {"release", "prepare_linux_repositories", "verify"},
            set(jobs["publish_linux_repositories"]["needs"]),
        )
        for name in ("prepare_linux_repositories", "release", "publish_linux_repositories"):
            guard = jobs[name]["if"]
            self.assertIn("github.ref_type == 'tag'", guard)
            self.assertIn("startsWith(github.ref, 'refs/tags/v')", guard)
        publish_guard = jobs["publish_linux_repositories"]["if"]
        self.assertIn("needs.release.result == 'success'", publish_guard)
        self.assertNotIn("workflow_dispatch", publish_guard)
        self.assertNotIn("if", jobs["linux_packages"])
        self.assertLess(self.text.index("  release:"), self.text.index("  publish_linux_repositories:"))

    def test_top_and_job_permissions_are_least_privilege(self):
        self.assertEqual({"contents": "read"}, self.loaded["permissions"])
        expected = {
            "verify": {"contents": "read"},
            "test": {"contents": "read"},
            "package": {"contents": "read"},
            "linux_packages": {"contents": "read"},
            "prepare_linux_repositories": {"contents": "read"},
            "release": {"contents": "write"},
            "publish_linux_repositories": {
                "contents": "write", "pages": "write", "id-token": "write"
            },
        }
        self.assertEqual(set(expected), set(self.loaded["jobs"]))
        for name, permissions in expected.items():
            self.assertEqual(permissions, self.loaded["jobs"][name]["permissions"])

    def test_release_actions_are_immutable_and_local_calls_are_exact(self):
        uses = re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", self.text)
        self.assertTrue(uses)
        allowed_local = {
            "./.github/workflows/linux-packages.yml",
            "./.github/workflows/publish-linux-repositories.yml",
        }
        for action in uses:
            with self.subTest(action=action):
                if action.startswith("./"):
                    self.assertIn(action, allowed_local)
                else:
                    self.assertRegex(action, ACTION_SHA)
        expected_pins = {
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            "actions/setup-dotnet@67a3573c9a986a3f9c594539f4ab511d57bb3ce9",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
        }
        self.assertTrue(expected_pins.issubset(set(uses)))

    def test_release_verifies_signed_packages_and_collects_every_asset_type(self):
        release = self.loaded["jobs"]["release"]
        steps = release["steps"]
        downloads = [step for step in steps if step.get("uses", "").startswith("actions/download-artifact@")]
        self.assertEqual(2, len(downloads))
        platform = next(step for step in downloads if step["with"].get("pattern") == "release-*")
        signed = next(step for step in downloads if step["with"].get("name") == "linux-release-packages")
        self.assertEqual("downloaded/platform", platform["with"]["path"])
        self.assertEqual("downloaded/linux-release-packages", signed["with"]["path"])

        collect = next(step["run"] for step in steps if step.get("name") == "Verify and collect release artifacts")
        for marker in (
            "sha256sum --check SHA256SUMS", "*.deb", "*.rpm", "*.tar.gz", "*.zip",
            "SHA256SUMS.txt", "ObjectStorageClient-${VERSION}-linux-x64.tar.gz",
            "ObjectStorageClient-${VERSION}-osx-arm64.zip",
            "ObjectStorageClient-${VERSION}-osx-x64.zip",
        ):
            self.assertIn(marker, collect)
        self.assertRegex(collect, r"find .* -name '\*\.deb'.*wc -l.*-eq 1")
        self.assertRegex(collect, r"find .* -name '\*\.rpm'.*wc -l.*-eq 1")
        self.assertLess(collect.index("sha256sum --check SHA256SUMS"), collect.index("mkdir -p artifacts"))
        self.assertIn("artifacts/*", steps[-1]["run"])
        for marker in ("Build MSIX for the Store", "Upload MSIX", "STORE_URL", "build/release-body.md"):
            self.assertIn(marker, self.text)

    def test_gpg_identifiers_are_configured_without_bypass_or_secret_dumping(self):
        combined = self.text + workflow_text(PUBLICATION_WORKFLOW)
        for identifier in (
            "LINUX_REPO_GPG_PRIVATE_KEY",
            "LINUX_REPO_GPG_PASSPHRASE",
            "LINUX_REPO_GPG_FINGERPRINT",
        ):
            self.assertIn(identifier, combined)
        lowered = combined.lower()
        for marker in ("trusted=yes", "--nogpgcheck", "printenv", "export -p", "echo $private", "echo $passphrase"):
            self.assertNotIn(marker, lowered)

    def test_release_multiline_bash_steps_parse(self):
        snippets = [
            step["run"]
            for job in self.loaded["jobs"].values()
            if "steps" in job
            for step in job["steps"]
            if "run" in step and step.get("shell", "bash") != "pwsh"
        ]
        self.assertTrue(snippets)
        for body in snippets:
            with tempfile.NamedTemporaryFile("w", suffix=".bash", encoding="utf-8") as script:
                script.write(body)
                script.flush()
                result = subprocess.run(["bash", "-n", script.name], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
