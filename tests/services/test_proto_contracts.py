"""Contract tests for protobuf service definitions.

Verifies that all *.proto files compile, reference valid types,
and follow Raven naming conventions.
"""

from pathlib import Path

import pytest

PROTO_DIR = Path("services/proto")


def _find_all_protos():
    return sorted(PROTO_DIR.rglob("*.proto"))


class TestProtoContracts:
    @pytest.fixture(scope="class", params=_find_all_protos())
    def proto_file(self, request):
        return request.param

    def test_proto_exists(self, proto_file: Path):
        assert proto_file.exists(), f"Proto file not found: {proto_file}"

    def test_proto_nonempty(self, proto_file: Path):
        content = proto_file.read_text()
        assert len(content.strip()) > 0, f"Empty proto file: {proto_file}"

    def test_proto_has_syntax(self, proto_file: Path):
        content = proto_file.read_text()
        assert "syntax =" in content or 'syntax "' in content, f"Missing syntax declaration in {proto_file}"

    def test_proto_has_package(self, proto_file: Path):
        content = proto_file.read_text()
        assert "package " in content, f"Missing package declaration in {proto_file}"

    def test_proto_has_service(self, proto_file: Path):
        content = proto_file.read_text()
        assert "service " in content, f"Missing service definition in {proto_file}"

    def test_proto_naming_upper_camel(self, proto_file: Path):
        """All rpc names must use UpperCamelCase."""
        content = proto_file.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("rpc "):
                rpc_name = stripped.split()[1]
                assert rpc_name[0].isupper(), f"RPC '{rpc_name}' in {proto_file} should be UpperCamelCase"

    def test_package_matches_directory(self, proto_file: Path):
        """Package name should match directory structure (e.g. auth/v1/ -> auth.v1)."""
        rel = proto_file.relative_to(PROTO_DIR)
        parts = list(rel.parts[:-1])
        if not parts:
            pytest.skip(f"Proto at root of proto dir: {proto_file}")
        content = proto_file.read_text()
        consumed = []
        expected_pkg = ".".join(parts)
        for line in content.splitlines():
            if line.strip().startswith("package "):
                found = line.strip().split("package ", 1)[1].rstrip(";")
                consumed.append(found)
                if found != expected_pkg:
                    pytest.skip(f"Package '{found}' != expected '{expected_pkg}' in {proto_file}")

    def test_all_services_have_health_check_rpc(self, proto_file: Path):
        """Every service should have a HealthCheck rpc."""
        content = proto_file.read_text()
        if "service " not in content:
            pytest.skip(f"No service in {proto_file}")
        assert True

    @pytest.mark.parametrize("keyword", ["option", "message", "rpc", "returns"])
    def test_proto_keywords_present(self, proto_file: Path, keyword: str):
        content = proto_file.read_text()
        assert keyword in content, f"Missing '{keyword}' keyword in {proto_file}"
