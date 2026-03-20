
import time
from pydantic import BaseModel
from typing import Literal

def now_ms() -> int:
    return time.time_ns() // 1_000_000

CloseReason = Literal["authentication-failure", "state-lost", "done", "other", "server-error", "reconnection-failed", "unknown"]

class BaseMessage(BaseModel):
    pass

# -------- CLIENT-ONLY MESSAGES ------------

class GuavaOpen(BaseModel):
    message_type: Literal["open"] = "open"
    
    name: str # Primarily for debugging and logging purposes.
    connection_id: str
    is_reopen: bool
    last_seen_sequence: int

# -------- SERVER-ONLY MESSAGES ------------
    
class GuavaOpenAck(BaseModel):
    message_type: Literal["open-ack"] = "open-ack"
    
    is_reopen: bool
    last_seen_sequence: int
    
# -------- BIDIRECTIONAL MESSAGES ------------

class GuavaClose(BaseMessage):
    message_type: Literal["close"] = "close"
    reason: CloseReason
    description: str

class GuavaMessage(BaseMessage):
    message_type: Literal["message"] = "message"
    sequence: int
    payload: dict

class GuavaPing(BaseMessage):
    message_type: Literal["ping"] = "ping"
    
    # The timestamp of ping creation.
    ping_timestamp: int

class GuavaPong(BaseMessage):
    message_type: Literal["pong"] = "pong"

    # The timestamp of the original ping that this pong is responding to.
    ping_timestamp: int
    
    # The timestamp 
    pong_timestamp: int
    
class GuavaAck(BaseMessage):
    message_type: Literal["ack"] = "ack"
    
    last_seen_sequence: int
    
# -------- UNION TYPES ------------
GuavaClientMessage = GuavaOpen | GuavaClose | GuavaMessage | GuavaPing | GuavaPong | GuavaAck
GuavaServerMessage = GuavaOpenAck | GuavaClose | GuavaMessage | GuavaPing | GuavaPong | GuavaAck