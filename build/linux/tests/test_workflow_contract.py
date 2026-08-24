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
        self.assertEqual({"prepare", "deployment_smoke", "publish"}, set(loaded["jobs"]))
        self.assertEqual({"contents": "read"}, loaded["jobs"]["prepare"]["permissions"])
        self.assertEqual({"contents": "read"}, loaded["jobs"]["deployment_smoke"]["permissions"])
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
            expected_mode = "prepare" if mode == "deployment_smoke" else mode
            self.assertIn(f"inputs.mode == '{expected_mode}'", guard)
            self.assertIn("timeout-minutes", job)
        self.assertEqual(35, loaded["jobs"]["deployment_smoke"]["timeout-minutes"])
        self.assertEqual("prepare", loaded["jobs"]["deployment_smoke"]["needs"])

    def test_deployment_smoke_matrix_uses_prepared_production_signed_artifacts(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        job = loaded["jobs"]["deployment_smoke"]
        include = job["strategy"]["matrix"]["include"]
        actual = {(entry["image"], entry["slug"], entry["kind"]) for entry in include}
        self.assertEqual(EXPECTED_MATRIX, actual)
        self.assertEqual(len(EXPECTED_MATRIX), len(include))
        self.assertEqual("false", job["strategy"]["fail-fast"])
        for entry in include:
            suffix = "deb" if entry["kind"] == "deb" else "rpm"
            self.assertEqual(
                f"ObjectStorageClient-${{{{ inputs.version }}}}-${{{{ inputs.package_release }}}}-linux-x64.{suffix}",
                entry["package"],
            )

        downloads = [
            step for step in job["steps"]
            if step.get("uses", "").startswith("actions/download-artifact@")
        ]
        self.assertEqual(2, len(downloads))
        candidate = next(
            step for step in downloads
            if step["with"].get("name") == "${{ inputs.candidate_artifact }}"
        )
        packages = next(
            step for step in downloads
            if step["with"].get("name") == "linux-release-packages"
        )
        self.assertEqual("artifacts/site", candidate["with"]["path"])
        self.assertEqual("artifacts/linux-smoke-packages", packages["with"]["path"])

        text = self.text()
        for marker in (
            "sha256sum --check SHA256SUMS",
            "docker network create",
            "--network-alias repository",
            "python:3-alpine python3 -m http.server 8000",
            "REPOSITORY_URL=http://repository:8000",
            "build/linux/smoke-package.sh",
            '"/repository"',
            "if: always()",
            "docker logs \"$server\"",
            "docker network rm",
            "name: linux-deployment-smoke-${{ matrix.slug }}",
        ):
            self.assertIn(marker, text)
        self.assertRegex(text, r"(?s)(?:while|for) .*repository:8000.*sleep")

        job_text = "\n".join(
            str(value) for step in job["steps"] for value in step.values()
        )
        self.assertNotIn("secrets.", job_text)
        self.assertNotIn("LINUX_REPO_GPG_PRIVATE_KEY", job_text)
        self.assertNotIn("LINUX_REPO_GPG_PASSPHRASE", job_text)

    def test_throwaway_and_deployment_smoke_matrices_are_distinct_gates(self):
        validation = load_workflow(WORKFLOW)["jobs"]["smoke"]
        deployment = load_workflow(PUBLICATION_WORKFLOW)["jobs"]["deployment_smoke"]
        self.assertEqual("build", validation["needs"])
        self.assertEqual("prepare", deployment["needs"])
        validation_downloads = {
            step.get("with", {}).get("name") for step in validation["steps"]
        }
        deployment_downloads = {
            step.get("with", {}).get("name") for step in deployment["steps"]
        }
        self.assertIn("linux-package-validation", validation_downloads)
        self.assertIn("linux-release-packages", deployment_downloads)
        self.assertIn("${{ inputs.candidate_artifact }}", deployment_downloads)

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

    def test_publish_deploys_and_reads_back_before_recording_pages_history(self):
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
        self.assertIsNotNone(loaded)
        assert loaded is not None
        names = [step["name"] for step in loaded["jobs"]["publish"]["steps"]]
        regenerate = names.index("Regenerate from latest gh-pages")
        upload = names.index("Upload Pages artifact")
        deploy = names.index("Deploy Pages artifact")
        readback = names.index("Read back and cryptographically verify every public repository object")
        history = names.index("Record verified Pages tree in gh-pages history")
        self.assertLess(regenerate, upload)
        self.assertLess(upload, deploy)
        self.assertLess(deploy, readback)
        self.assertLess(readback, history)

        steps = loaded["jobs"]["publish"]["steps"]
        before_history = "\n".join(step.get("run", "") for step in steps[:history])
        self.assertNotRegex(before_history, r"(?m)^\s*git(?:\s+-C\s+\S+)?\s+push\b")
        history_script = steps[history]["run"]
        self.assertIn("git fetch origin +refs/heads/gh-pages:refs/remotes/origin/gh-pages", history_script)
        self.assertIn("rsync -a --delete --exclude .git deployment/site/ pages/", history_script)
        self.assertIn('git -C pages commit -m "Publish Linux packages ${VERSION}-${PACKAGE_RELEASE}"', history_script)
        self.assertIn("git push origin HEAD:gh-pages", history_script)
        self.assertNotRegex(history_script, r"git push[^\n]*(?:--force|-f\b)")

    def test_current_rpm_identity_is_checked_before_pages_upload(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        steps = loaded["jobs"]["publish"]["steps"]
        names = [step["name"] for step in steps]
        validation = next(step for step in steps if step.get("name") == "Validate current RPM identity")
        script = validation["run"]
        self.assertLess(names.index("Regenerate from latest gh-pages"), names.index("Validate current RPM identity"))
        self.assertLess(names.index("Validate current RPM identity"), names.index("Upload Pages artifact"))
        self.assertIn("rpm -qp --qf", script)
        self.assertIn("%{NAME}\\t%{VERSION}\\t%{RELEASE}\\t%{ARCH}\\n", script)
        self.assertEqual("${{ inputs.package_release }}", validation["env"]["PACKAGE_RELEASE"])
        self.assertEqual("${{ inputs.version }}", validation["env"]["VERSION"])
        self.assertIn("object-storage-client", script)
        self.assertIn("x86_64", script)
        self.assertIn("RPM_RELEASE_WITH_DIST", script)

    def test_public_primary_parser_accepts_only_safe_optional_dist_suffix(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        step = next(
            step for step in loaded["jobs"]["publish"]["steps"]
            if step.get("name") == "Read back and cryptographically verify every public repository object"
        )
        matches = list(re.finditer(
            r"python3 - \"\$primary_file\".*?<<'PY'\n(?P<body>.*?)\nPY",
            step["run"], re.DOTALL,
        ))
        self.assertEqual(1, len(matches))
        parser = matches[0].group("body")
        self.assertIn("RPM_RELEASE_WITH_DIST", parser)
        compile(parser, "<primary-parser>", "exec")

        def run(release: str) -> subprocess.CompletedProcess[str]:
            with tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                primary = root / "primary.xml"
                primary.write_text(
                    f'''<metadata><package><name>object-storage-client</name><arch>x86_64</arch>
                    <version ver="1.0.0" rel="{release}"/><location href="package.rpm"/>
                    <checksum type="sha256">{'0' * 64}</checksum><size package="3"/></package></metadata>''',
                    encoding="utf-8",
                )
                return subprocess.run(
                    ["python3", "-c", parser, str(primary), str(root / "manifest"), "1.0.0", "1"],
                    capture_output=True, text=True,
                )

        for release in ("1", "1.fc44"):
            with self.subTest(release=release):
                result = run(release)
                self.assertEqual(0, result.returncode, result.stderr)
        for release in ("10", "1evil", "1.."):
            with self.subTest(release=release):
                self.assertNotEqual(0, run(release).returncode)

    def test_pages_preconfiguration_is_get_only_and_precedes_publication(self):
        loaded = load_workflow(PUBLICATION_WORKFLOW)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        steps = loaded["jobs"]["publish"]["steps"]
        names = [step["name"] for step in steps]
        verify_index = names.index("Verify Pages is preconfigured")
        publish_index = names.index("Regenerate from latest gh-pages")
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
                "verify", "test", "package", "linux_packages", "rhel_release_gate",
                "prepare_linux_repositories", "release", "publish_linux_repositories",
            },
            set(self.loaded["jobs"]),
        )

        linux = self.loaded["jobs"]["linux_packages"]
        self.assertEqual("verify", linux["needs"])
        self.assertEqual("./.github/workflows/linux-packages.yml", linux["uses"])
        self.assertEqual(
            {
                "version": "${{ needs.verify.outputs.version }}",
                "package_release": "${{ needs.verify.outputs.package_release }}",
            },
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
                    "package_release": "${{ needs.verify.outputs.package_release }}",
                    "validation_artifact": "linux-package-validation",
                    "candidate_artifact": "linux-pages-candidate",
                },
                job["with"],
            )
            self.assertEqual(expected_secrets, job["secrets"])

        gate = self.loaded["jobs"]["rhel_release_gate"]
        self.assertEqual("verify", gate["needs"])
        self.assertEqual("ubuntu-latest", gate["runs-on"])
        self.assertEqual("rhel-9-manual-validation", gate["environment"])
        self.assertEqual(10, gate["timeout-minutes"])
        self.assertEqual({"contents": "read"}, gate["permissions"])
        self.assertIn("github.ref_type == 'tag'", gate["if"])
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", gate["if"])

        self.assertEqual(1, len(gate["steps"]))
        step = gate["steps"][0]
        self.assertEqual(
            {"VALIDATED_VERSION": "${{ vars.RHEL9_MANUAL_VALIDATION_VERSION }}"},
            step["env"],
        )
        script = step["run"]
        self.assertEqual("set -euo pipefail", script.splitlines()[0])
        self.assertIn('[[ -n "$VALIDATED_VERSION" ]]', script)
        self.assertIn(
            '[[ "$VALIDATED_VERSION" == "${{ needs.verify.outputs.version }}-${{ needs.verify.outputs.package_release }}" ]]',
            script,
        )
        self.assertNotIn("secrets.", str(gate))
        self.assertNotIn("$VALIDATED_VERSION", "\n".join(
            line for line in script.splitlines() if "error" in line.lower()
        ))
        self.assertIn("required reviewer", self.text.lower())
        self.assertIn("subscribed RHEL 9", self.text)
        self.assertIn("GUI, S3,", self.text)
        self.assertIn("native package validation", self.text)
        self.assertEqual(
            "${{ steps.version.outputs.package_release }}",
            self.loaded["jobs"]["verify"]["outputs"]["package_release"],
        )
        self.assertIn(
            '[[ "$VALIDATED_VERSION" == "${{ needs.verify.outputs.version }}-${{ needs.verify.outputs.package_release }}" ]]',
            script,
        )

    def test_tag_parser_supports_native_release_suffix_and_manual_defaults_to_one(self):
        step = self.loaded["jobs"]["verify"]["steps"][-1]
        script = step["run"]
        self.assertIn("RELEASE_TAG_PATTERN", script)
        self.assertIn("NativeVersion.parse", script)
        match = re.search(r"python3 - .*?<<'PY'\n(?P<body>.*?)\nPY", script, re.DOTALL)
        self.assertIsNotNone(match)
        assert match is not None
        parser = match.group("body")
        compile(parser, "<release-tag-parser>", "exec")
        props = ROOT / "Directory.Build.props"
        props_match = re.search(r"<Version>([^<]+)</Version>", props.read_text(encoding="utf-8"))
        self.assertIsNotNone(props_match)
        assert props_match is not None
        actual = props_match.group(1)

        def run(ref_type: str, ref_name: str, props_version: str = actual):
            with tempfile.TemporaryDirectory() as directory:
                output = pathlib.Path(directory) / "output"
                result = subprocess.run(
                    ["python3", "-c", parser, ref_type, ref_name, props_version, str(output)],
                    cwd=ROOT, capture_output=True, text=True,
                )
                values = dict(
                    line.split("=", 1)
                    for line in output.read_text(encoding="utf-8").splitlines()
                ) if output.exists() else {}
                return result, values

        for tag, expected_release in ((f"v{actual}", "1"), (f"v{actual}-2", "2")):
            result, values = run("tag", tag)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual({"version": actual, "package_release": expected_release}, values)
        result, values = run("branch", "main")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"version": actual, "package_release": "1"}, values)
        for tag in (
            f"v{actual}-0", f"v{actual}-65536", f"v{actual}-999999999999999999999999",
            f"v{actual}-x", f"v{actual}-1-2",
        ):
            self.assertNotEqual(0, run("tag", tag)[0].returncode, tag)
        self.assertNotEqual(0, run("tag", "v9.9.9-2")[0].returncode)

    def test_dependency_order_tag_guards_and_manual_safety_are_exact(self):
        jobs = self.loaded["jobs"]
        self.assertEqual(
            {"verify", "linux_packages", "rhel_release_gate"},
            set(jobs["prepare_linux_repositories"]["needs"]),
        )
        self.assertEqual(
            {"verify", "package", "linux_packages", "prepare_linux_repositories"},
            set(jobs["release"]["needs"]),
        )
        self.assertEqual(
            {"release", "prepare_linux_repositories", "verify"},
            set(jobs["publish_linux_repositories"]["needs"]),
        )
        for name in ("rhel_release_gate", "prepare_linux_repositories", "release", "publish_linux_repositories"):
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
            "rhel_release_gate": {"contents": "read"},
            "prepare_linux_repositories": {"contents": "read"},
            "release": {"contents": "write"},
            "publish_linux_repositories": {
                "contents": "write", "pages": "write", "id-token": "write"
            },
        }
        self.assertEqual(set(expected), set(self.loaded["jobs"]))
        for name, permissions in expected.items():
            self.assertEqual(permissions, self.loaded["jobs"][name]["permissions"])

    def test_release_executable_jobs_have_bounded_timeouts(self):
        expected = {"verify": 10, "test": 30, "package": 35, "rhel_release_gate": 10, "release": 15}
        for name, timeout in expected.items():
            self.assertEqual(timeout, self.loaded["jobs"][name]["timeout-minutes"])
        for name in ("linux_packages", "prepare_linux_repositories", "publish_linux_repositories"):
            self.assertIn("uses", self.loaded["jobs"][name])

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

    def test_release_verifies_and_collects_the_exact_asset_set_without_overwrite(self):
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
            "ObjectStorageClient-${VERSION}-${PACKAGE_RELEASE}-linux-x64.deb",
            "ObjectStorageClient-${VERSION}-${PACKAGE_RELEASE}-linux-x64.rpm",
            "duplicate release asset basename", "unexpected release asset set",
            "mv -n --", 'test ! -e "$source"', 'test -f "$destination"',
        ):
            self.assertIn(marker, collect)
        self.assertIn('test "${#assets[@]}" -eq 5', collect)
        collect_step = next(
            step for step in steps if step.get("name") == "Verify and collect release artifacts"
        )
        self.assertEqual(
            "${{ needs.verify.outputs.package_release }}",
            collect_step["env"]["PACKAGE_RELEASE"],
        )
        self.assertLess(collect.index("sha256sum --check SHA256SUMS"), collect.index("mkdir artifacts"))
        self.assertLess(collect.index("unexpected release asset set"), collect.index("mkdir artifacts"))
        self.assertLess(collect.index("test ! -e artifacts"), collect.index("mkdir artifacts"))
        self.assertIn("artifacts/*", steps[-1]["run"])
        for marker in ("Build MSIX for the Store", "Upload MSIX", "STORE_URL", "build/release-body.md"):
            self.assertIn(marker, self.text)
        for marker in ("@STORE_URL_KO@", "@STORE_URL_EN@", "Not published yet", "아직 공개되지 않았다"):
            self.assertIn(marker, self.text + (ROOT / "build/release-body.md").read_text(encoding="utf-8"))
        self.assertIn("@PACKAGE_RELEASE@", (ROOT / "build/release-body.md").read_text(encoding="utf-8"))
        self.assertIn(".replace('@PACKAGE_RELEASE@', package_release)", self.text)
        self.assertIn("if '@' in rendered", self.text)

    def test_release_collector_rejects_duplicate_missing_and_extra_before_mutation(self):
        steps = self.loaded["jobs"]["release"]["steps"]
        collect = next(step["run"] for step in steps if step.get("name") == "Verify and collect release artifacts")
        version = "9.8.7"
        package_release = "2"
        expected = [
            f"ObjectStorageClient-{version}-linux-x64.tar.gz",
            f"ObjectStorageClient-{version}-osx-arm64.zip",
            f"ObjectStorageClient-{version}-osx-x64.zip",
            f"ObjectStorageClient-{version}-{package_release}-linux-x64.deb",
            f"ObjectStorageClient-{version}-{package_release}-linux-x64.rpm",
        ]

        for scenario in ("duplicate", "missing", "extra", "success"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                platform = root / "downloaded/platform"
                signed = root / "downloaded/linux-release-packages"
                platform.mkdir(parents=True)
                signed.mkdir(parents=True)
                names = list(expected)
                if scenario == "missing":
                    names.remove(expected[1])
                if scenario == "extra":
                    names.append(f"ObjectStorageClient-{version}-debug.zip")
                for name in names:
                    path = signed / name if name.endswith((".deb", ".rpm")) else platform / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name, encoding="utf-8")
                if scenario == "duplicate":
                    duplicate = platform / "duplicate" / expected[1]
                    duplicate.parent.mkdir(parents=True)
                    duplicate.write_text("duplicate", encoding="utf-8")
                checksummed = [path for path in signed.iterdir() if path.suffix in (".deb", ".rpm")]
                sums = subprocess.run(
                    ["sha256sum", "--", *[path.name for path in checksummed]],
                    cwd=signed, check=True, capture_output=True, text=True,
                ).stdout
                (signed / "SHA256SUMS").write_text(sums, encoding="utf-8")

                result = subprocess.run(
                    ["bash", "-c", collect], cwd=root,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "VERSION": version,
                        "PACKAGE_RELEASE": package_release,
                    },
                    capture_output=True, text=True,
                )
                if scenario == "success":
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(set(expected + ["SHA256SUMS.txt"]), {path.name for path in (root / "artifacts").iterdir()})
                    self.assertFalse(any(path.is_file() and path.name in expected for path in (root / "downloaded").rglob("*")))
                else:
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse((root / "artifacts").exists())

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

    def test_release_calls_do_not_hardcode_package_release_one(self):
        for job in ("linux_packages", "prepare_linux_repositories", "publish_linux_repositories"):
            self.assertEqual(
                "${{ needs.verify.outputs.package_release }}",
                self.loaded["jobs"][job]["with"]["package_release"],
            )
        self.assertNotRegex(self.text, r"package_release:\s*'1'")
        self.assertNotIn("-${VERSION}-1-linux-x64", self.text)


if __name__ == "__main__":
    unittest.main()
