from app.core.errors import AppError
from app.models import Property, User, UserRole


def can_manage_property(user: User, prop: Property) -> bool:
    return user.role == UserRole.ADMIN or (user.role == UserRole.SELLER and prop.created_by == user.id)


def ensure_can_manage_property(user: User, prop: Property) -> None:
    if not can_manage_property(user, prop):
        raise AppError("You do not have permission to manage this property.", "FORBIDDEN", 403)
