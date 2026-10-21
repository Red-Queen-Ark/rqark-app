
from rqark_core.types.provider import Provider

from rqark_app.app import AgentApp
from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.session.storage import CloudStorage, JSONLStorage
from rqark_app.types.cloud import CloudConfig


def client() -> RQArkDataCloudClient:
    return RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'token'))


def test_a_cloud_storage_supplies_the_client():
    cloud = client()
    app = AgentApp([Provider('m', 'http://x', 0, 'k')], CloudStorage(cloud))
    assert app.cloud_client is cloud


def test_a_local_storage_has_no_client():
    app = AgentApp([Provider('m', 'http://x', 0, 'k')], JSONLStorage('/tmp/rqark-test-sessions'))
    assert app.cloud_client is None


def test_an_explicit_none_keeps_the_provider_key_in_use():
    app = AgentApp([Provider('m', 'http://x', 0, 'k')], CloudStorage(client()), cloud_client=None)
    assert app.cloud_client is None


def test_an_explicit_client_wins_over_the_storage():
    chosen = client()
    app = AgentApp([Provider('m', 'http://x', 0, 'k')], CloudStorage(client()), cloud_client=chosen)
    assert app.cloud_client is chosen
