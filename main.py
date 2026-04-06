import os
from dotenv import load_dotenv
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq # <-- Αλλαγή σε Groq

# 1. Φόρτωση κλειδιών
load_dotenv()

# 2. Ορισμός Κατάστασης (State)
class State(TypedDict):
    messages: Annotated[list, "Η λίστα των μηνυμάτων"]

# 3. Ορισμός του Llama (Meta) μέσω Groq
llm = ChatGroq(model_name="llama-3.3-70b-versatile")

# 4. Λειτουργία Πράκτορα
def assistant(state: State):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}

# 5. Χτίσιμο Γραφήματος (LangGraph) 
builder = StateGraph(State)
builder.add_node("assistant", assistant)
builder.add_edge(START, "assistant")
builder.add_edge("assistant", END)

graph = builder.compile()

if __name__ == "__main__":
    print("--- Ο Llama Agent (Meta) είναι έτοιμος! ---")
    user_input = "Γεια σου! Είσαι ο βοηθός μου για τη διπλωματική;"
    
    # Τρέχουμε τον πράκτορα
    events = graph.stream({"messages": [("user", user_input)]})
    for event in events:
        for value in event.values():
            print("Assistant:", value["messages"][-1].content)