"""HTTP contract double: identity state lives outside the CBS database."""

import json
from threading import Lock
from uuid import UUID, uuid4

import httpx

from infrastructure.customer_service_client import CustomerServiceClient


class CustomerServiceFake:
    def __init__(self):
        self.records = {}
        self.unavailable = False
        self.lose_response = False
        self.calls = []
        self._lock = Lock()
        self.client = CustomerServiceClient(
            "https://customers.test",
            "a" * 64,
            transport=httpx.MockTransport(self.handle),
        )

    def handle(self, request):
        with self._lock:
            return self._handle(request)

    def _handle(self, request):
        self.calls.append(request)
        if self.unavailable:
            raise httpx.ConnectError("service unavailable")
        if request.method == "POST":
            body = json.loads(request.content)
            actor = UUID(body.pop("actor_id"))
            body.pop("session_token", None)
            if actor not in self.records:
                self.records[actor] = (uuid4(), body)
            customer, original = self.records[actor]
            if original != body:
                return httpx.Response(409)
            if self.lose_response:
                raise httpx.ReadTimeout("response lost after remote commit")
            return httpx.Response(
                200,
                json={
                    "actor_id": str(actor),
                    "customer_id": str(customer),
                    "status": "LINKED",
                },
            )
        if "/actors/" in request.url.path:
            actor = UUID(request.url.path.split("/")[-2])
            existing = self.records.get(actor)
            return httpx.Response(
                200,
                json={
                    "actor_id": str(actor),
                    "customer_id": str(existing[0]) if existing else None,
                    "status": "LINKED" if existing else "PENDING_LINK",
                },
            )
        customer = UUID(request.url.path.split("/")[-1])
        exists = any(record[0] == customer for record in self.records.values())
        return (
            httpx.Response(200, json={"customer_id": str(customer)})
            if exists
            else httpx.Response(404)
        )
