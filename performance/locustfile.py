"""Locust workload for the order fulfilment API.

The workload mixes read traffic, transactional writes, idempotent replays,
state transitions and authentication traffic so that the performance report
reflects realistic API usage instead of a single hot endpoint.
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task

PRODUCT_IDS = [1, 2, 3, 4, 5, 6, 7, 10, 11, 12]
ORDER_STATUSES = ["", "CREATED", "PICKING", "SHIPPED", "COMPLETED"]
SEARCH_TERMS = ["", "耳机", "鼠标", "SKU-1004", "设备", "办公"]
CATEGORIES = ["", "电脑外设", "音频设备", "桌面设备"]

OPERATOR_USER = os.getenv("PERF_OPERATOR_USER", "operator")
OPERATOR_PASSWORD = os.getenv("PERF_OPERATOR_PASSWORD", "Operator@123")
ADMIN_USER = os.getenv("PERF_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("PERF_ADMIN_PASSWORD", "Admin@123")


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ApiUser(HttpUser):
    abstract = True
    wait_time = between(0.2, 0.8)

    def on_start(self) -> None:
        self.token = self.login(OPERATOR_USER, OPERATOR_PASSWORD)

    def login(self, username: str, password: str) -> str:
        with self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            name="POST /api/v1/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login failed: {response.status_code}")
                return ""
            payload = response.json()
            token = payload.get("data", {}).get("access_token", "")
            if not token:
                response.failure("missing access token")
            return token

    def headers(self) -> dict[str, str]:
        return auth_headers(self.token) if self.token else {}


class ReadUser(ApiUser):
    weight = 5

    @task(6)
    def browse_products(self) -> None:
        params = {
            "page": random.randint(1, 2),
            "page_size": random.choice([10, 20, 50]),
            "search": random.choice(SEARCH_TERMS),
            "category": random.choice(CATEGORIES),
        }
        with self.client.get(
            "/api/v1/products",
            params=params,
            headers=self.headers(),
            name="GET /api/v1/products",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")
            elif not response.json().get("success"):
                response.failure("success=false")

    @task(3)
    def product_detail(self) -> None:
        product_id = random.choice(PRODUCT_IDS)
        with self.client.get(
            f"/api/v1/products/{product_id}",
            headers=self.headers(),
            name="GET /api/v1/products/{id}",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(3)
    def dashboard(self) -> None:
        with self.client.get(
            "/api/v1/dashboard/summary",
            headers=self.headers(),
            name="GET /api/v1/dashboard/summary",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(2)
    def order_queue(self) -> None:
        status = random.choice(ORDER_STATUSES)
        params = {"page_size": 20}
        if status:
            params["status"] = status
        with self.client.get(
            "/api/v1/orders",
            params=params,
            headers=self.headers(),
            name="GET /api/v1/orders",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(1)
    def health(self) -> None:
        with self.client.get(
            "/health/live",
            name="GET /health/live",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")


class WriteUser(ApiUser):
    weight = 3

    def create_order(
        self,
        idempotency_key: str,
        expect_replay: bool | None = None,
        expected_order_id: int | None = None,
        product_id: int | None = None,
    ) -> tuple[int | None, bool]:
        selected_product = product_id or random.choice([1, 4])
        payload = {
            "items": [{"product_id": selected_product, "quantity": 1}],
            "remark": f"locust-{idempotency_key[:8]}",
        }
        with self.client.post(
            "/api/v1/orders",
            json=payload,
            headers={**self.headers(), "Idempotency-Key": idempotency_key},
            name="POST /api/v1/orders",
            catch_response=True,
        ) as response:
            if response.status_code not in {200, 201}:
                response.failure(f"status={response.status_code}")
                return None, False
            body = response.json()
            if not body.get("success"):
                response.failure("success=false")
                return None, False
            order_id = int(body["data"]["id"])
            replayed = bool(body.get("meta", {}).get("idempotent_replay"))
            if expect_replay is not None and replayed != expect_replay:
                response.failure(
                    f"expected idempotent_replay={expect_replay}, got {replayed}"
                )
            if expected_order_id is not None and order_id != expected_order_id:
                response.failure(
                    f"expected order {expected_order_id}, got {order_id}"
                )
            return order_id, replayed

    def cancel_order(self, order_id: int) -> None:
        with self.client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers=self.headers(),
            name="POST /api/v1/orders/{id}/cancel",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(5)
    def create_and_cancel(self) -> None:
        order_id, _ = self.create_order(uuid.uuid4().hex)
        if order_id is not None:
            self.cancel_order(order_id)

    @task(2)
    def idempotent_replay(self) -> None:
        key = uuid.uuid4().hex
        product_id = random.choice([1, 4])
        order_id, _ = self.create_order(
            key, expect_replay=False, product_id=product_id
        )
        if order_id is None:
            return
        self.create_order(
            key,
            expect_replay=True,
            expected_order_id=order_id,
            product_id=product_id,
        )
        self.cancel_order(order_id)

    @task(2)
    def fulfilment_chain(self) -> None:
        order_id, _ = self.create_order(uuid.uuid4().hex)
        if order_id is None:
            return
        for status in ("PICKING", "SHIPPED", "COMPLETED"):
            with self.client.patch(
                f"/api/v1/orders/{order_id}/status",
                json={"status": status},
                headers=self.headers(),
                name="PATCH /api/v1/orders/{id}/status",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"status={response.status_code}")
                    return


class AuthUser(ApiUser):
    weight = 1

    def on_start(self) -> None:
        self.token = self.login(ADMIN_USER, ADMIN_PASSWORD)

    @task(4)
    def login_success(self) -> None:
        username = random.choice([OPERATOR_USER, ADMIN_USER])
        password = OPERATOR_PASSWORD if username == OPERATOR_USER else ADMIN_PASSWORD
        with self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            name="POST /api/v1/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")

    @task(2)
    def login_failure(self) -> None:
        with self.client.post(
            "/api/v1/auth/login",
            json={"username": "performance-probe", "password": "Wrong@1234"},
            name="POST /api/v1/auth/login[invalid]",
            catch_response=True,
        ) as response:
            if response.status_code != 401:
                response.failure(f"status={response.status_code}")
            else:
                response.success()
