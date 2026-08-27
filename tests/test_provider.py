from rqark_core.types.provider import Provider
from rqark_app.provider.manager import ProviderManager

providers = [
    Provider('', '', '', 1, name='p1'),
    Provider('', '', '', 2, name='p2'),
    Provider('', '', '', 4, name='p3'),
    Provider('', '', '', 3, name='p4'),
]
provider_mgr = ProviderManager(providers)

# INIT INFO
assert provider_mgr.provider.name == 'p1'

# Sort List
assert provider_mgr.providers[2].name == 'p4'

# Auto Switch Provider
provider_mgr.report_failure()
assert provider_mgr.provider.name == 'p1'

provider_mgr.report_failure()
provider_mgr.report_failure()
assert provider_mgr.provider.name == 'p2'

# User Switch Provider
provider_mgr.switch_to(0)
assert provider_mgr.provider.name == 'p1'

provider_mgr.switch_to(4)
assert provider_mgr.provider.name == 'p1'


provider_mgr.switch_to(1)
assert provider_mgr.provider.name == 'p2'
