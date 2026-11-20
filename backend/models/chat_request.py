
from pydantic import BaseModel, Field


class ChatHistoryMessage(BaseModel):
    id: str | None = None
    client_message_id: str | None = None
    role: str
    content: str
    metadata: dict = Field(default_factory=dict)


class ChatRequest(BaseModel):
    content: str
    history: list[ChatHistoryMessage] = Field(default_factory=list)
