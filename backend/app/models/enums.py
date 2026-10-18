import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    SELLER = "SELLER"
    BIDDER = "BIDDER"


class PropertyStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    IN_AUCTION = "IN_AUCTION"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    WITHDRAWN = "WITHDRAWN"


class AuctionStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    LIVE = "LIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class BidStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
