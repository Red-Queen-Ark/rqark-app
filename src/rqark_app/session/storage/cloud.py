from rqark_core.types.tool import PlanItem

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.types.session import Session, message_from_dict, parse_dt

from .base import SessionStorage


class CloudStorage(SessionStorage):
    def __init__(self, client: RQArkDataCloudClient):
        self.client = client

    async def create(self, session: Session) -> None:
        await self.client.create_session(self._metadata(session))

    async def save(self, session: Session) -> None:
        payload = self._payload(session)
        try:
            await self.client.update_session(session.uuid, payload)
            return
        except DataCloudError as error:
            if error.status_code != 404:
                raise
        await self.client.create_session(self._metadata(session))
        await self.client.update_session(session.uuid, payload)

    async def load(self) -> list[Session]:
        return [await self._restore(info) for info in await self.client.list_sessions()]

    async def delete(self, session_id: str) -> bool:
        try:
            await self.client.delete_session(session_id)
        except DataCloudError as error:
            if error.status_code == 404:
                return False
            raise
        return True

    def _payload(self, session: Session) -> dict:
        payload = session.to_dict()
        payload.pop('created_at', None)
        payload.pop('updated_at', None)
        return payload

    def _metadata(self, session: Session) -> dict:
        payload = self._payload(session)
        payload.pop('history', None)
        return payload

    async def _restore(self, info: dict) -> Session:
        messages = await self.client.list_session_messages(info['id'])
        return Session(
            uuid=info['id'],
            created_at=parse_dt(info['created_at']),
            updated_at=parse_dt(info['updated_at']),
            title=info.get('title') or '',
            plan_items=[PlanItem(**item) for item in info.get('plan_items') or []],
            history=[message_from_dict(message['data']) for message in messages],
        )
