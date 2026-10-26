"""所有 Schema 汇总"""
from .chat import (
    ChatRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    ConversationUpdate,
    FeedbackCreate,
    GlobalChatRequest,
    MessageResponse,
    Source,
)
from .document import DocumentListResponse, DocumentResponse
from .knowledge_base import (
    KBCreate,
    KBDetail,
    KbMemberInvite,
    KbMemberList,
    KbMemberResponse,
    KBResponse,
    KBUpdate,
)
from .structured import AnswerTemplate, StructuredRequest, StructuredResponse
from .user import (
    ModelUpdate,
    PasswordUpdate,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from .wiki import (
    WikiGraphEdge,
    WikiGraphNode,
    WikiGraphResponse,
    WikiPageEditRequest,
    WikiPageListItem,
    WikiPageResponse,
    WikiRecompileResponse,
    WikiRollbackResponse,
    WikiVersionResponse,
)

__all__ = [
    "UserCreate", "UserLogin", "UserResponse", "TokenResponse",
    "PasswordUpdate", "ModelUpdate",
    "KBCreate", "KBUpdate", "KBResponse", "KBDetail",
    "KbMemberInvite", "KbMemberResponse", "KbMemberList",
    "DocumentResponse", "DocumentListResponse",
    "ChatRequest", "Source", "MessageResponse",
    "ConversationCreate", "ConversationUpdate",
    "ConversationResponse", "ConversationDetail",
    "FeedbackCreate", "GlobalChatRequest",
    "WikiPageResponse", "WikiPageListItem", "WikiGraphResponse",
    "WikiGraphNode", "WikiGraphEdge", "WikiRecompileResponse",
    "WikiPageEditRequest", "WikiVersionResponse", "WikiRollbackResponse",
    "StructuredRequest", "StructuredResponse", "AnswerTemplate",
]
