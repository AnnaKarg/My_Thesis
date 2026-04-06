from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from database.session import AsyncSessionLocal
from database.models import User, ChatHistory
from core.app import app as langgraph_app
from langchain_core.messages import HumanMessage

router = APIRouter()

async def get_db():
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()

@router.post("/chat/{username}")
async def chat(username: str, message: str, db: AsyncSession = Depends(get_db)):

    result = await db.execute(select(User).filter(User.username == username))
    user = result.scalars().first()
    
    if not user:
        user = User(username=username, current_lesson_id=1)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    state = {
        "messages": [HumanMessage(content=message)],
        "student_code": "", # Εδώ θα μπαίνει ο κώδικας του φοιτητή αργότερα
        "debug_report": "",
        "is_correct": False,
        "current_lesson": "Variables"
    }

    try:

        output = await langgraph_app.ainvoke(
            state, 
            config={"recursion_limit": 5}
        )
        ai_response = output["messages"][-1].content
    except Exception as e:
        print(f"Σφάλμα στο Graph: {e}")
        ai_response = "Συγγνώμη, μπερδεύτηκα λίγο. Μπορείς να μου ξαναπείς τι θέλεις να κάνουμε;"

    new_msg_user = ChatHistory(user_id=user.id, role="human", content=message)
    new_msg_ai = ChatHistory(user_id=user.id, role="ai", content=ai_response)
    
    db.add_all([new_msg_user, new_msg_ai])
    await db.commit()

    return {"mentor_response": ai_response}