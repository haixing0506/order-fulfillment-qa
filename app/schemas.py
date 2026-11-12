from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class OrderItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=99)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[OrderItemCreate] = Field(min_length=1, max_length=20)
    remark: str = Field(default="", max_length=200)

    @field_validator("remark")
    @classmethod
    def trim_remark(cls, value: str) -> str:
        return value.strip()


class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(PICKING|SHIPPED|COMPLETED)$")


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=2, max_length=80)
    category: str = Field(min_length=2, max_length=40)
    price_cents: int = Field(ge=1, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)


class StockUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stock: int = Field(ge=0, le=1_000_000)

