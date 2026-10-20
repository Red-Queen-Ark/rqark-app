from rqark_core.types.provider import Provider

from rqark_app.provider.manager import ProviderManager


def make_manager() -> ProviderManager:
    providers = [Provider('', '', 1, name='p1'), Provider('', '', 2, name='p2'), Provider('', '', 4, name='p3'), Provider('', '', 3, name='p4')]
    return ProviderManager(providers)


def test_initial_provider_is_lowest_priority():
    assert make_manager().provider.name == 'p1'


def test_providers_sorted_by_priority():
    mgr = make_manager()
    assert mgr.providers[2].name == 'p4'


def test_report_failure_does_not_switch_before_max_retries():
    mgr = make_manager()
    mgr.report_failure()
    assert mgr.provider.name == 'p1'


def test_report_failure_switches_after_max_retries():
    mgr = make_manager()
    mgr.report_failure()
    mgr.report_failure()
    mgr.report_failure()
    assert mgr.provider.name == 'p2'


def test_switch_to_current_index_keeps_provider():
    mgr = make_manager()
    assert mgr.switch_to(0) is True
    assert mgr.provider.name == 'p1'


def test_switch_to_out_of_range_is_rejected():
    mgr = make_manager()
    assert mgr.switch_to(4) is False
    assert mgr.provider.name == 'p1'


def test_switch_to_valid_index_changes_provider():
    mgr = make_manager()
    assert mgr.switch_to(1) is True
    assert mgr.provider.name == 'p2'
