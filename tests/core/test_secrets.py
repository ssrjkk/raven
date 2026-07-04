import os
import shutil
from pathlib import Path

import pytest

from raven.core.secrets import SecretsManager


@pytest.fixture
def mgr():
    os.environ["RAVEN_MASTER_KEY"] = "test-master-key-for-testing-only"
    data_dir = "tmp_test_secrets"
    manager = SecretsManager(data_dir=data_dir)
    yield manager
    os.environ.pop("RAVEN_MASTER_KEY", None)
    shutil.rmtree(data_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_get_default(mgr):
    assert mgr.get("nonexistent") == ""


@pytest.mark.asyncio
async def test_get_custom_default(mgr):
    assert mgr.get("nonexistent", "fallback") == "fallback"


@pytest.mark.asyncio
async def test_set_and_get(mgr):
    await mgr.set("API_KEY", "sk-test")
    assert mgr.get("API_KEY") == "sk-test"


@pytest.mark.asyncio
async def test_set_overwrites(mgr):
    await mgr.set("KEY", "v1")
    await mgr.set("KEY", "v2")
    assert mgr.get("KEY") == "v2"


@pytest.mark.asyncio
async def test_unset(mgr):
    await mgr.set("KEY", "value")
    await mgr.unset("KEY")
    assert mgr.get("KEY") == ""


@pytest.mark.asyncio
async def test_unset_nonexistent(mgr):
    await mgr.unset("nonexistent")


@pytest.mark.asyncio
async def test_list_keys(mgr):
    await mgr.set("A", "1")
    await mgr.set("B", "2")
    keys = mgr.list_keys()
    assert "A" in keys
    assert "B" in keys


@pytest.mark.asyncio
async def test_load_once(mgr):
    await mgr.load()
    assert mgr._loaded is True
    await mgr.load()


@pytest.mark.asyncio
async def test_decrypt_raises_on_failure(mgr):
    from raven.core.secrets import _MARKER

    with pytest.raises(RuntimeError, match="Secrets decryption failed"):
        mgr.decrypt(_MARKER + "invalidciphertext")


@pytest.mark.asyncio
async def test_encrypt_decrypt_roundtrip(mgr):
    original = "super-secret-value"
    encrypted = mgr.encrypt(original)
    assert encrypted.startswith("enc:")
    decrypted = mgr.decrypt(encrypted)
    assert decrypted == original


@pytest.mark.asyncio
async def test_persistence_across_reload(mgr):
    await mgr.set("persist_key", "persist_value")
    data_dir = mgr._data_dir

    mgr2 = SecretsManager(data_dir=str(data_dir))
    await mgr2.load()
    assert mgr2.get("persist_key") == "persist_value"


@pytest.mark.asyncio
async def test_save_file_atomic(mgr):
    await mgr.set("k1", "v1")
    enc_file = mgr._enc_path
    assert enc_file.exists()
    content = enc_file.read_text()
    assert "k1" in content
    assert not enc_file.with_suffix(".enc.tmp").exists()
