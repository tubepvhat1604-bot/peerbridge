from fastapi import APIRouter, Depends, HTTPException, Path

from ..schemas import MatchSearchResponse
from ..security import current_user
from ..services.matches import (
    MatchProfileNotFoundError,
    MatchRequestNotFoundError,
    MatchSearchForbiddenError,
    MatchSearchService,
    get_match_search_service,
)

router = APIRouter(prefix="/matches", tags=["matches"])


def _match_http_error(error: Exception) -> HTTPException:
    if isinstance(error, MatchSearchForbiddenError):
        return HTTPException(status_code=403, detail="Only students can search matches")
    if isinstance(error, (MatchProfileNotFoundError, MatchRequestNotFoundError)):
        return HTTPException(status_code=404, detail="Match request not found")
    return HTTPException(status_code=500, detail="Could not process match request")


@router.post("/search", response_model=MatchSearchResponse, status_code=201)
def search_matches(
    user: dict = Depends(current_user),
    service: MatchSearchService = Depends(get_match_search_service),
) -> MatchSearchResponse:
    try:
        return service.search_matches(user)
    except (MatchProfileNotFoundError, MatchSearchForbiddenError) as error:
        raise _match_http_error(error) from error


@router.get("/{request_id}", response_model=MatchSearchResponse)
def get_match_request(
    request_id: int = Path(gt=0),
    user: dict = Depends(current_user),
    service: MatchSearchService = Depends(get_match_search_service),
) -> MatchSearchResponse:
    try:
        return service.get_match_request(user, request_id)
    except (MatchRequestNotFoundError, MatchSearchForbiddenError) as error:
        raise _match_http_error(error) from error
