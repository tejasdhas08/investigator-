"""Stage 4: interactive Q&A."""
import hashlib
import pathlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_case_for_user, get_current_user
from app.models.case import Case
from app.models.chat import ChatMessage
from app.models.user import User
from app.pipeline.narrative_guard import _event_index, extract_citations
from app.schemas.api import ChatAskRequest, ChatMessageOut, Page
from app.services import audit, chat_context, llm, timeline_builder

router = APIRouter(prefix="/cases/{case_id}/chat", tags=["chat"])

QA_SYSTEM = (pathlib.Path(__file__).resolve().parent.parent / "prompts" / "qa.txt").read_text()


@router.post("")
def ask(
    body: ChatAskRequest,
    case: Case = Depends(get_case_for_user),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if case.status != "complete":
        raise HTTPException(409, detail={"error": "case_not_ready",
                                         "message": "Q&A is available once analysis is complete"})
    # Store the question first so history survives an LLM outage (Stage 4 error handling).
    question_msg = ChatMessage(case_id=case.id, user_id=user.id, role="user", content=body.question)
    db.add(question_msg)
    db.commit()

    timeline = timeline_builder.build_timeline(db, case, exclude_rejected=True)
    timeline_dict = timeline.model_dump()
    blocks, _level = chat_context.assemble(db, case, timeline_dict, body.question)
    try:
        answer_text = llm.complete(
            system=QA_SYSTEM, user_blocks=blocks, model=settings.qa_model,
            max_tokens=2000, temperature=0.3,
        )
    except Exception:
        db.commit()  # keep the stored question
        raise HTTPException(503, detail={"error": "qa_unavailable", "retry_after_s": 30,
                                         "message": "Q&A temporarily unavailable"})

    citations = extract_citations(answer_text, _event_index(timeline))
    answer = ChatMessage(
        case_id=case.id, role="assistant", content=answer_text,
        citations=citations, model=settings.qa_model,
        token_count=llm.rough_token_count(answer_text),
    )
    db.add(answer)
    audit.log(db, action="ai.chat.answer", actor_type="ai", case_id=case.id,
              entity_type="chat_message",
              detail={
                  "question": body.question,
                  "answer_sha256": hashlib.sha256(answer_text.encode()).hexdigest(),
                  "cited_event_ids": [c["event_id"] for c in citations],
                  "model_id": settings.qa_model,
              })
    db.commit()
    db.refresh(answer)
    return {"message": ChatMessageOut.model_validate(answer), "citations": citations}


@router.get("", response_model=Page[ChatMessageOut])
def history(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 100,
):
    from sqlalchemy import func

    stmt = select(ChatMessage).where(ChatMessage.case_id == case.id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(ChatMessage.created_at).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return Page(items=rows, total=total, page=page, page_size=page_size)
