from __future__ import annotations

from ..ports.persistence import UowFactory


class KnowledgeService:
    def __init__(self, uow: UowFactory):
        self.uow = uow

    async def search(
        self,
        query: str,
        material_id: str | None = None,
        property_name: str | None = None,
        conditions: str = "",
        offset: int = 0,
    ):
        async with self.uow() as uow:
            records = await uow.knowledge.search(query, material_id, property_name, offset)
        exact = [
            r for r in records if not conditions or r.conditions.casefold() == conditions.casefold()
        ]
        values = {(r.value, r.unit, r.conditions) for r in exact}
        status = "not_found"
        if records:
            ambiguous = (
                len(values) > 1
                or len(exact) != len(records)
                or any(r.scope == "family" for r in records)
            )
            status = "ambiguous" if ambiguous else "found"
        return {
            "status": status,
            "records": [r.model_dump() for r in records],
            "next_offset": offset + 5 if len(records) == 5 else None,
            "limitations": ["KB-001", "Свойства семейства не подтверждают свойства точной марки"],
        }
