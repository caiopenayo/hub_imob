from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


SaleScopeType = Literal["full_city", "priority_neighborhoods"]


@dataclass(frozen=True)
class PriorityNeighborhood:
    name: str
    slug: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


SALE_PRIORITY_NEIGHBORHOODS: tuple[PriorityNeighborhood, ...] = (
    PriorityNeighborhood(name="Pinheiros", slug="pinheiros"),
    PriorityNeighborhood(name="Vila Madalena", slug="vila-madalena"),
    PriorityNeighborhood(name="Perdizes", slug="perdizes"),
    PriorityNeighborhood(name="Pompeia", slug="pompeia"),
    PriorityNeighborhood(name="Sumaré", slug="sumare"),
    PriorityNeighborhood(name="Butantã", slug="butanta"),
)


@dataclass(frozen=True)
class SaleScrapeScope:
    state: str = "SP"
    state_slug: str = "sp"
    city: str = "São Paulo"
    city_slug: str = "sao-paulo"
    purpose: Literal["sale"] = "sale"
    scope_type: SaleScopeType = "full_city"
    neighborhoods: tuple[PriorityNeighborhood, ...] = field(default_factory=tuple)

    @classmethod
    def full_city(cls) -> "SaleScrapeScope":
        return cls(scope_type="full_city")

    @classmethod
    def priority_neighborhoods(cls) -> "SaleScrapeScope":
        return cls(scope_type="priority_neighborhoods", neighborhoods=SALE_PRIORITY_NEIGHBORHOODS)

    @classmethod
    def priority_neighborhood(cls, neighborhood: PriorityNeighborhood) -> "SaleScrapeScope":
        return cls(scope_type="priority_neighborhoods", neighborhoods=(neighborhood,))

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "state": self.state,
            "state_slug": self.state_slug,
            "city": self.city,
            "city_slug": self.city_slug,
            "purpose": self.purpose,
            "scope_type": self.scope_type,
            "sync_offer_purposes": [self.purpose],
        }
        if self.neighborhoods:
            data["neighborhoods"] = [item.as_dict() for item in self.neighborhoods]
        return data
