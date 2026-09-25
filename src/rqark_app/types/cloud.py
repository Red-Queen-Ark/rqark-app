from dataclasses import dataclass


@dataclass
class CloudConfig:
    enabled: bool = True
    url: str = ''
    api_key: str = ''

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.url and self.api_key)
