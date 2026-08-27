from rqark_core.types.provider import Provider

class ProviderManager:
    def __init__(self, providers: list[Provider]):
        self.providers: list[Provider] = sorted(providers, key=lambda p: p.priority)
        self.cur_index = 0
        self.retry: int = 0
        self.max_retries: int = 3

    @property
    def provider(self) -> Provider:
        return self.providers[self.cur_index]

    def report_failure(self) -> None:
        self.retry += 1
        if self.retry >= self.max_retries:
            self._switch_provider()
            self.retry = 0

    def _switch_provider(self) -> None:
        self.cur_index += 1
        if self.cur_index >= len(self.providers):
            self.cur_index = 0

    def switch_to(self, index: int) -> bool:
        if index < 0 or index >= len(self.providers):
            return False
        if index == self.cur_index:
            return True
        self.cur_index = index
        self.retry = 0
        return True