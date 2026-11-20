from pydantic import BaseModel
class MessageRequest(BaseModel):
    role: str
    content: str