import pytest

from shield_api.config import ConfigConflict, ConfigStore, GatewayAlreadyRunning, GatewayRuntimeLock
from shield_api.db import Database

from test_contracts import REGISTRY, config_doc


@pytest.mark.asyncio
async def test_atomic_apply_poll_and_conflict(tmp_path):
    db = Database(tmp_path / "shield.sqlite3")
    await db.initialize()
    store = ConfigStore(db, REGISTRY, clock=lambda: 1000)
    assert store.snapshot is None
    first = await store.apply_config(None, config_doc(), "admin")
    assert first.desired_version == 1 and first.applied_version is None
    with pytest.raises(ConfigConflict):
        await store.apply_config(None, config_doc(), "admin")
    assert (await store.status()).status == "stale"
    applied = await store.poll_and_apply()
    assert applied.version == 1
    await store.heartbeat("instance", 1000, 0)
    assert (await store.status()).status == "applied"
    document = config_doc()
    document["service"]["name"] = "Renamed"
    second = await store.apply_config(1, document, "admin")
    assert second.desired_version == 2 and second.applied_version == 1
    assert (await store.status()).status == "pending"
    assert store.snapshot.version == 1
    assert (await store.poll_and_apply()).version == 2
    assert (await store.status()).status == "applied"
    await db.close()


@pytest.mark.asyncio
async def test_service_id_immutable_and_failed_apply_has_no_revision(tmp_path):
    db = Database(tmp_path / "shield.sqlite3")
    await db.initialize()
    store = ConfigStore(db, REGISTRY, clock=lambda: 1000)
    await store.apply_config(None, config_doc(), "admin")
    document = config_doc()
    document["service"]["id"] = "other"
    with pytest.raises(ValueError):
        await store.apply_config(1, document, "admin")
    assert (await store.load_desired())[0] == 1
    await db.close()


def test_single_gateway_runtime_lock(tmp_path):
    first = GatewayRuntimeLock(tmp_path)
    second = GatewayRuntimeLock(tmp_path)
    with first:
        with pytest.raises(GatewayAlreadyRunning):
            second.acquire()
    with second:
        pass
