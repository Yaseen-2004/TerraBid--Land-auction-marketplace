from pydantic import BaseModel

from app.schemas.common import Money


class DashboardStats(BaseModel):
    total_properties: int
    active_auctions: int
    upcoming_auctions: int
    completed_auctions: int
    cancelled_auctions: int
    registered_users: int
    total_bids: int
    rejected_bids: int
    total_sales_value: Money
