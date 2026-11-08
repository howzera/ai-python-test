from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from app.domain.exceptions import RequestNotFoundError
from app.domain.models import RequestStatus
from app.infrastructure.http_api.schemas import CreateRequestBody, RequestCreated, RequestStatusResponse

router = APIRouter(prefix="/v1/requests", tags=["requests"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RequestCreated)
async def create_request(body: CreateRequestBody, request: Request) -> RequestCreated:
    created = await request.app.state.create_request.execute(body.user_input)
    return RequestCreated(id=created.id)


@router.post(
    "/{request_id}/process",
    response_model=RequestStatusResponse,
    responses={200: {"description": "Already finished"}, 202: {"description": "Accepted or in progress"}, 404: {}},
)
async def process_request(request_id: str, request: Request, response: Response) -> RequestStatusResponse:
    processed = await request.app.state.process_request.execute(request_id)
    # 202: the work continues in the background. 200: it had already finished.
    finished = processed.status in (RequestStatus.SENT, RequestStatus.FAILED)
    response.status_code = status.HTTP_200_OK if finished else status.HTTP_202_ACCEPTED
    return RequestStatusResponse(id=processed.id, status=processed.status)


@router.get("/{request_id}", response_model=RequestStatusResponse)
async def get_request(request_id: str, request: Request) -> RequestStatusResponse:
    found = await request.app.state.get_request.execute(request_id)
    return RequestStatusResponse(id=found.id, status=found.status)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestNotFoundError)
    async def not_found(_: Request, error: RequestNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})
