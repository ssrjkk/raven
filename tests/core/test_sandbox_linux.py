from __future__ import annotations

import sys

from raven.core.sandbox_linux import (
    CgroupConfig,
    NsJailConfig,
    SeccompProfile,
    detect_cgroups_v2,
    detect_nsjail,
    detect_seccomp,
    get_available_sandboxes,
    recommended_profile,
)


def test_seccomp_profile_defaults():
    p = SeccompProfile()
    assert not p.allow_network
    assert not p.allow_exec
    assert p.allow_read
    assert p.allow_write
    assert p.extra_syscalls == []


def test_seccomp_profile_to_dict():
    p = SeccompProfile(allow_network=True, extra_syscalls=["clone", "mount"])
    d = p.to_dict()
    assert d["allow_network"]
    assert "clone" in d["extra_syscalls"]


def test_cgroup_config_defaults():
    c = CgroupConfig()
    assert c.memory_max_bytes == 512 * 1024 * 1024
    assert c.cpu_max_percent == 50.0
    assert c.pids_max == 64


def test_cgroup_config_to_dict():
    c = CgroupConfig(memory_max_bytes=256 * 1024 * 1024)
    d = c.to_dict()
    assert d["memory_max_bytes"] == 256 * 1024 * 1024


def test_nsjail_config_defaults():
    n = NsJailConfig()
    assert not n.enabled
    assert n.time_limit_seconds == 30
    assert n.clone_newnet
    assert n.clone_newuser


def test_nsjail_config_to_dict():
    n = NsJailConfig(enabled=True, chroot_dir="/opt/jail")
    d = n.to_dict()
    assert d["enabled"]
    assert d["chroot_dir"] == "/opt/jail"


def test_nsjail_config_to_cfg():
    n = NsJailConfig(enabled=True, time_limit_seconds=15, chroot_dir="/jail")
    cfg = n.to_nsjail_cfg()
    assert "time_limit: 15" in cfg
    assert "chroot: /jail" in cfg


def test_detect_seccomp_on_windows():
    if sys.platform == "win32":
        assert not detect_seccomp()
    else:
        assert isinstance(detect_seccomp(), bool)


def test_detect_nsjail():
    assert isinstance(detect_nsjail(), bool)


def test_detect_cgroups_v2():
    assert isinstance(detect_cgroups_v2(), bool)


def test_get_available_sandboxes():
    avail = get_available_sandboxes()
    assert "subprocess" in avail
    assert avail["subprocess"]
    assert "docker" in avail
    assert "nsjail" in avail
    assert "seccomp" in avail
    assert "cgroups_v2" in avail


def test_recommended_profile():
    profile = recommended_profile()
    assert "backend" in profile
    assert profile["backend"] in ("subprocess", "docker", "nsjail", "none")


def test_seccomp_profile_custom():
    p = SeccompProfile(
        allow_read=False,
        allow_write=False,
        allow_network=True,
        allow_exec=True,
        allow_fs=True,
        extra_syscalls=["ptrace"],
    )
    assert not p.allow_read
    assert p.allow_network
    assert p.extra_syscalls == ["ptrace"]
