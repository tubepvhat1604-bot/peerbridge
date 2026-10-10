from collections.abc import Generator

from ..cache import cache
from ..db import database, utc_now
from ..repositories.profiles import ProfileRepository
from ..schemas import (
    Availability,
    HelpNeed,
    HelpOffer,
    Profile,
    ProfileMeResponse,
    ProfileMeUpdate,
    ProfileUpdate,
)
from .content_safety import reject_personal_contact


class ProfileNotFoundError(Exception):
    """Raised when the authenticated user does not have a profile row."""


class ProfileAccessDeniedError(Exception):
    """Raised when a user tries to mutate a profile they do not own."""


class ProfileService:
    def __init__(self, repository: ProfileRepository) -> None:
        self.repository = repository

    def get_my_profile(self, user: dict) -> ProfileMeResponse:
        user_id = self._current_user_id(user)
        bundle = self.repository.get_profile_bundle(user_id)
        if not bundle:
            raise ProfileNotFoundError("Profile not found")
        return ProfileMeResponse(
            profile=Profile(**bundle["profile"]),
            needs_help_with=[HelpNeed(**item) for item in bundle["needs_help_with"]],
            can_help_with=[HelpOffer(**item) for item in bundle["can_help_with"]],
            availability=[Availability(**item) for item in bundle["availability"]],
        )

    def update_my_profile(self, user: dict, payload: ProfileMeUpdate | ProfileUpdate) -> ProfileMeResponse:
        user_id = self._current_user_id(user)
        updated_at = utc_now()

        if isinstance(payload, ProfileMeUpdate):
            reject_personal_contact(payload.profile.bio, "Phần giới thiệu")
            updated = self.repository.replace_peerbridge_profile(user_id, payload, updated_at)
        else:
            reject_personal_contact(payload.bio, "Phần giới thiệu")
            updated = self.repository.update_legacy_profile(user_id, payload, updated_at)

        if not updated:
            raise ProfileNotFoundError("Profile not found")

        cache.delete_prefix(f"discover:{user_id}:")
        return self.get_my_profile(user)

    @staticmethod
    def _current_user_id(user: dict) -> int:
        user_id = int(user["id"])
        requested_user_id = user.get("user_id", user_id)
        if int(requested_user_id) != user_id:
            raise ProfileAccessDeniedError("Students can only update their own profile")
        return user_id


def get_profile_service() -> Generator[ProfileService, None, None]:
    with database() as connection:
        yield ProfileService(ProfileRepository(connection))
