"""PostgreSQL-backed cold store for durable TaskPlane state."""

from __future__ import annotations

from typing import Any

from ..protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus
from ._model_codec import dump_model, utcnow


class PgColdStore:
    def __init__(self, *, database_url: str) -> None:
        self._database_url = database_url
        self._engine = None
        self._initialized = False

    async def save_envelope(self, envelope: PlanEnvelope) -> None:
        await self._execute_upsert(self._envelope_table(), dump_model(envelope), ("envelope_id",))

    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None:
        row = await self._fetch_one(self._select_table(self._envelope_table(), envelope_id=envelope_id))
        if row is None:
            return None
        return PlanEnvelope.model_validate(dict(row))

    async def save_ticket(self, ticket: TaskTicket) -> None:
        await self._execute_upsert(self._ticket_table(), self._ticket_payload(ticket), ("ticket_id",))

    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None:
        for ticket in tickets:
            await self.save_ticket(ticket)

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        row = await self._fetch_one(self._select_table(self._ticket_table(), ticket_id=ticket_id))
        if row is None:
            return None
        result = await self.get_result(ticket_id)
        return self._ticket_from_row(dict(row), result=result)

    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]:
        query = self._ordered_ticket_query().where(self._ticket_table().c.envelope_id == envelope_id)
        rows = await self._fetch_all(query)
        return [self._ticket_from_row(dict(row)) for row in rows]

    async def update_status(
        self,
        ticket_id: str,
        status: TicketStatus,
        **kwargs: Any,
    ) -> TaskTicket:
        update_values = {"status": status.value, "updated_at": utcnow(), **kwargs}
        await self._execute_update(ticket_id, update_values)
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            raise ValueError(f"unknown_ticket: {ticket_id}")
        return ticket

    async def claim_next(
        self,
        labels: dict[str, str] | None = None,
        batch_size: int = 1,
    ) -> list[TaskTicket]:
        select, update = self._sqlalchemy("select", "update")
        table = self._ticket_table()
        query = self._ordered_ticket_query().where(table.c.status == TicketStatus.QUEUED.value)
        if labels:
            query = query.where(table.c.labels.contains(labels))
        query = query.limit(max(batch_size, 0)).with_for_update(skip_locked=True)
        engine = await self._engine_ready()
        async with engine.begin() as conn:
            rows = list((await conn.execute(query)).mappings())
            ticket_ids = [str(row["ticket_id"]) for row in rows]
            if ticket_ids:
                await conn.execute(
                    update(table)
                    .where(table.c.ticket_id.in_(ticket_ids))
                    .values(status=TicketStatus.DISPATCHED.value, updated_at=utcnow())
                )
        return [ticket for ticket_id in ticket_ids if (ticket := await self.get_ticket(ticket_id)) is not None]

    async def release_claim(self, ticket_id: str, reason: str) -> None:
        del reason
        await self.update_status(ticket_id, TicketStatus.QUEUED, assigned_to=None)

    async def save_result(self, result: TaskResult) -> None:
        await self._execute_upsert(self._result_table(), dump_model(result), ("result_id",))

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        select = self._sqlalchemy("select")[0]
        table = self._result_table()
        query = select(table).where(table.c.ticket_id == ticket_id).order_by(table.c.completed_at.desc()).limit(1)
        row = await self._fetch_one(query)
        if row is None:
            return None
        return TaskResult.model_validate(dict(row))

    async def query_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]:
        query = self._ordered_ticket_query()
        table = self._ticket_table()
        if status is not None:
            query = query.where(table.c.status == status.value)
        if envelope_id is not None:
            query = query.where(table.c.envelope_id == envelope_id)
        if labels:
            query = query.where(table.c.labels.contains(labels))
        rows = await self._fetch_all(query.limit(limit))
        return [self._ticket_from_row(dict(row)) for row in rows]

    async def aclose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._initialized = False

    def _ticket_payload(self, ticket: TaskTicket) -> dict[str, Any]:
        payload = dump_model(ticket)
        payload.pop("result", None)
        payload["status"] = ticket.status.value
        return payload

    def _ticket_from_row(self, row: dict[str, Any], *, result: TaskResult | None = None) -> TaskTicket:
        row["status"] = TicketStatus(row["status"])
        row["result"] = result
        return TaskTicket.model_validate(row)

    async def _execute_upsert(self, table, payload: dict[str, Any], conflict_keys: tuple[str, ...]) -> None:
        insert = self._sqlalchemy("insert")[0]
        engine = await self._engine_ready()
        stmt = insert(table).values(**payload)
        updates = {key: value for key, value in payload.items() if key not in conflict_keys}
        stmt = stmt.on_conflict_do_update(index_elements=list(conflict_keys), set_=updates)
        async with engine.begin() as conn:
            await conn.execute(stmt)

    async def _execute_update(self, ticket_id: str, payload: dict[str, Any]) -> None:
        update = self._sqlalchemy("update")[0]
        table = self._ticket_table()
        engine = await self._engine_ready()
        async with engine.begin() as conn:
            await conn.execute(update(table).where(table.c.ticket_id == ticket_id).values(**payload))

    async def _fetch_one(self, query):
        engine = await self._engine_ready()
        async with engine.connect() as conn:
            return (await conn.execute(query)).mappings().first()

    async def _fetch_all(self, query):
        engine = await self._engine_ready()
        async with engine.connect() as conn:
            return list((await conn.execute(query)).mappings())

    async def _engine_ready(self):
        if self._engine is None:
            create_async_engine = self._sqlalchemy("create_async_engine")[0]
            self._engine = create_async_engine(self._normalized_database_url())
        if not self._initialized:
            await self._create_tables()
            self._initialized = True
        return self._engine

    async def _create_tables(self) -> None:
        metadata = self._schema("metadata")[0]
        engine = self._engine
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    def _ordered_ticket_query(self):
        select = self._sqlalchemy("select")[0]
        table = self._ticket_table()
        return select(table).order_by(table.c.priority.asc(), table.c.created_at.asc())

    def _select_table(self, table, **filters: Any):
        query = self._ordered_ticket_query() if table is self._ticket_table() else self._sqlalchemy("select")[0](table)
        for key, value in filters.items():
            query = query.where(getattr(table.c, key) == value)
        return query.limit(1)

    def _envelope_table(self):
        return self._schema("plan_envelopes")[0]

    def _ticket_table(self):
        return self._schema("task_tickets")[0]

    def _result_table(self):
        return self._schema("task_results")[0]

    def _normalized_database_url(self) -> str:
        return self._schema("normalize_database_url")[0](self._database_url)

    @staticmethod
    def _sqlalchemy(*names: str):
        from sqlalchemy import select, update
        from sqlalchemy.dialects.postgresql import insert
        from sqlalchemy.ext.asyncio import create_async_engine

        mapping = {
            "create_async_engine": create_async_engine,
            "insert": insert,
            "select": select,
            "update": update,
        }
        return tuple(mapping[name] for name in names)

    @staticmethod
    def _schema(*names: str):
        from ._pg_schema import metadata, normalize_database_url, plan_envelopes, task_results, task_tickets

        mapping = {
            "metadata": metadata,
            "normalize_database_url": normalize_database_url,
            "plan_envelopes": plan_envelopes,
            "task_results": task_results,
            "task_tickets": task_tickets,
        }
        return tuple(mapping[name] for name in names)
