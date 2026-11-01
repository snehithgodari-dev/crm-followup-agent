import asyncio
import json
import os
from typing import TypedDict

from dotenv import load_dotenv
from groq import Groq

from langgraph.graph import StateGraph, START, END

from mcp_client import call_tool


load_dotenv()


# ============================================================
# STATE
# ============================================================

class AgentState(TypedDict):
    user_message: str
    tool_name: str
    tool_arguments: dict
    tool_result: str
    response: str


# ============================================================
# GROQ
# ============================================================

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


MODEL_NAME = "openai/gpt-oss-20b"


# ============================================================
# TOOL DEFINITIONS FOR THE LLM
# ============================================================

TOOLS = [
    {
        "name": "get_dashboard",
        "description": "Get CRM dashboard KPIs and overall business analysis.",
        "arguments": {}
    },
    {
        "name": "get_customers",
        "description": "Get all customers.",
        "arguments": {}
    },
    {
        "name": "get_customer",
        "description": "Get one customer by customer ID.",
        "arguments": {
            "customer_id": "integer"
        }
    },
    {
        "name": "get_quotations",
        "description": "Get all quotations.",
        "arguments": {}
    },
    {
        "name": "get_pending_quotations",
        "description": "Get quotations requiring action.",
        "arguments": {}
    },
    {
        "name": "get_purchase_orders",
        "description": "Get all purchase orders.",
        "arguments": {}
    },
    {
        "name": "get_deliveries",
        "description": "Get all deliveries and their status.",
        "arguments": {}
    },
    {
        "name": "get_invoices",
        "description": "Get all invoices.",
        "arguments": {}
    },
    {
        "name": "get_overdue_invoices",
        "description": "Get invoices whose payment is overdue.",
        "arguments": {}
    },
    {
        "name": "get_pending_payments",
        "description": "Get pending, partial and overdue payments.",
        "arguments": {}
    },
    {
        "name": "get_followups",
        "description": "Get CRM follow-up history.",
        "arguments": {}
    },
    {
        "name": "send_reminder",
        "description": "Send payment reminder email for an overdue invoice.",
        "arguments": {
            "invoice_id": "integer"
        }
    },
    {
        "name": "make_payment",
        "description": "Record a payment against an invoice.",
        "arguments": {
            "invoice_id": "integer",
            "amount": "number",
            "payment_method": "string",
            "reference_number": "string"
        }
    }
]


# ============================================================
# NODE 1 — DECIDE TOOL
# ============================================================

def decide_tool(state: AgentState):

    user_message = state["user_message"]

    prompt = f"""
You are a CRM assistant.

You have access to these CRM tools:

{json.dumps(TOOLS, indent=2)}

User request:
{user_message}

Choose the ONE tool that should be called.

Return ONLY valid JSON in this exact format:

{{
    "tool_name": "tool name",
    "arguments": {{}}
}}

Do not write anything else.
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": prompt
            }
        ],
        temperature=0
    )

    text = response.choices[0].message.content.strip()

    # Remove markdown fences if the model adds them
    text = text.replace("```json", "")
    text = text.replace("```", "")
    text = text.strip()

    decision = json.loads(text)

    return {
        "tool_name": decision["tool_name"],
        "tool_arguments": decision.get(
            "arguments",
            {}
        )
    }


# ============================================================
# NODE 2 — CALL MCP
# ============================================================

def call_mcp(state: AgentState):

    result = asyncio.run(
        call_tool(
            state["tool_name"],
            state["tool_arguments"]
        )
    )

    return {
        "tool_result": str(result)
    }


# ============================================================
# NODE 3 — GENERATE RESPONSE
# ============================================================

def generate_response(state: AgentState):

    prompt = f"""
You are a professional CRM assistant.

User asked:
{state["user_message"]}

CRM tool used:
{state["tool_name"]}

CRM data:
{state["tool_result"]}

Answer the user clearly and concisely.

Use ₹ for Indian currency.

Do not invent information.

If there are no records, clearly say so.

IMPORTANT FORMATTING RULE:
- Do NOT use Markdown tables.
- For multiple CRM records, use a short bullet list.
- For pending/overdue invoices, show invoice number, customer, amount, due date and status as bullets.
- Keep the response easy to scan.
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": prompt
            }
        ],
        temperature=0.2
    )

    return {
        "response": response.choices[0].message.content
    }


# ============================================================
# BUILD LANGGRAPH
# ============================================================

def build_graph():

    graph = StateGraph(AgentState)

    graph.add_node(
        "decide_tool",
        decide_tool
    )

    graph.add_node(
        "call_mcp",
        call_mcp
    )

    graph.add_node(
        "generate_response",
        generate_response
    )

    graph.add_edge(
        START,
        "decide_tool"
    )

    graph.add_edge(
        "decide_tool",
        "call_mcp"
    )

    graph.add_edge(
        "call_mcp",
        "generate_response"
    )

    graph.add_edge(
        "generate_response",
        END
    )

    return graph.compile()


# ============================================================
# CHAT FUNCTION
# ============================================================

def run_agent(message: str):

    graph = build_graph()

    result = graph.invoke(
        {
            "user_message": message,
            "tool_name": "",
            "tool_arguments": {},
            "tool_result": "",
            "response": "",
        }
    )

    return result["response"]


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("CRM LANGGRAPH AGENT")
    print("=" * 60)

    question = "What are my overdue invoices?"

    print(f"\nUser: {question}\n")

    answer = run_agent(question)

    print("Assistant:")
    print(answer)

    print("\n" + "=" * 60)