from pydantic import BaseModel, Field, field_validator

from app.domain.models import RequestStatus

MAX_USER_INPUT_LENGTH = 2000


class CreateRequestBody(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=MAX_USER_INPUT_LENGTH)

    @field_validator("user_input")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_input must not be blank")
        return value


class RequestCreated(BaseModel):
    id: str


class RequestStatusResponse(BaseModel):
    id: str
    status: RequestStatus
