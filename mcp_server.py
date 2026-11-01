from mcp.server.mcpserver import MCPServer

from database.db import SessionLocal
from database.models import (
    Customer,
    Quotation,
    PurchaseOrder,
    Delivery,
    Invoice,
    FollowUp,
)

from services.payment_service import (
    record_payment,
    refresh_overdue_invoices,
)

from services.reminder_service import send_payment_reminder


server = MCPServer(name="CRM Follow-Up Server")


# =========================
# CUSTOMERS
# =========================

@server.tool()
def get_customers():
    """Get all CRM customers."""

    db = SessionLocal()
    try:
        customers = db.query(Customer).all()

        return [
            {
                "id": c.id,
                "company_name": c.company_name,
                "contact_person": c.contact_person,
                "email": c.email,
                "phone": c.phone,
                "gstin": c.gstin,
            }
            for c in customers
        ]
    finally:
        db.close()


@server.tool()
def get_customer(customer_id: int):
    """Get customer by ID."""

    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(
            Customer.id == customer_id
        ).first()

        if not customer:
            return {"success": False, "message": "Customer not found"}

        return {
            "success": True,
            "id": customer.id,
            "company_name": customer.company_name,
            "contact_person": customer.contact_person,
            "email": customer.email,
            "phone": customer.phone,
            "gstin": customer.gstin,
            "address": customer.address,
        }
    finally:
        db.close()


# =========================
# QUOTATIONS
# =========================

@server.tool()
def get_quotations():
    """Get all quotations."""

    db = SessionLocal()
    try:
        quotations = db.query(Quotation).all()

        return [
            {
                "id": q.id,
                "quotation_number": q.quotation_number,
                "customer": q.customer.company_name if q.customer else None,
                "amount": q.total_amount,
                "status": q.status,
                "date": str(q.quotation_date),
            }
            for q in quotations
        ]
    finally:
        db.close()


@server.tool()
def get_pending_quotations():
    """Get quotations requiring action."""

    db = SessionLocal()
    try:
        quotations = db.query(Quotation).filter(
            Quotation.status.in_(
                ["DRAFT", "SENT", "AWAITING_PO"]
            )
        ).all()

        return [
            {
                "id": q.id,
                "quotation_number": q.quotation_number,
                "customer": q.customer.company_name if q.customer else None,
                "amount": q.total_amount,
                "status": q.status,
            }
            for q in quotations
        ]
    finally:
        db.close()


# =========================
# PURCHASE ORDERS
# =========================

@server.tool()
def get_purchase_orders():
    """Get all purchase orders."""

    db = SessionLocal()
    try:
        pos = db.query(PurchaseOrder).all()

        return [
            {
                "id": po.id,
                "po_number": po.po_number,
                "quotation_id": po.quotation_id,
                "customer": po.customer.company_name if po.customer else None,
                "amount": po.total_amount,
                "payment_terms": po.payment_terms,
                "payment_days": po.payment_days,
                "status": po.status,
            }
            for po in pos
        ]
    finally:
        db.close()


# =========================
# DELIVERIES
# =========================

@server.tool()
def get_deliveries():
    """Get all deliveries."""

    db = SessionLocal()
    try:
        deliveries = db.query(Delivery).all()

        return [
            {
                "id": d.id,
                "purchase_order_id": d.purchase_order_id,
                "status": d.delivery_status,
                "expected_date": str(d.expected_date)
                if d.expected_date else None,
                "actual_date": str(d.actual_date)
                if d.actual_date else None,
                "remarks": d.remarks,
            }
            for d in deliveries
        ]
    finally:
        db.close()


# =========================
# INVOICES
# =========================

@server.tool()
def get_invoices():
    """Get all invoices."""

    db = SessionLocal()
    try:
        invoices = db.query(Invoice).all()

        return [
            {
                "id": i.id,
                "invoice_number": i.invoice_number,
                "customer": i.customer.company_name if i.customer else None,
                "purchase_order_id": i.purchase_order_id,
                "amount": i.total_amount,
                "invoice_date": str(i.invoice_date),
                "due_date": str(i.due_date) if i.due_date else None,
                "status": i.status,
            }
            for i in invoices
        ]
    finally:
        db.close()


@server.tool()
def get_overdue_invoices():
    """Get all overdue invoices."""

    db = SessionLocal()
    try:
        invoices = db.query(Invoice).filter(
            Invoice.status == "OVERDUE"
        ).all()

        return [
            {
                "id": i.id,
                "invoice_number": i.invoice_number,
                "customer": i.customer.company_name if i.customer else None,
                "email": i.customer.email if i.customer else None,
                "amount": i.total_amount,
                "due_date": str(i.due_date) if i.due_date else None,
                "status": i.status,
            }
            for i in invoices
        ]
    finally:
        db.close()


@server.tool()
def get_pending_payments():
    """Get pending, partial and overdue invoices."""

    db = SessionLocal()
    try:
        invoices = db.query(Invoice).filter(
            Invoice.status.in_(
                ["PENDING", "PARTIAL", "OVERDUE"]
            )
        ).all()

        return [
            {
                "id": i.id,
                "invoice_number": i.invoice_number,
                "customer": i.customer.company_name if i.customer else None,
                "amount": i.total_amount,
                "due_date": str(i.due_date) if i.due_date else None,
                "status": i.status,
            }
            for i in invoices
        ]
    finally:
        db.close()


# =========================
# PAYMENTS
# =========================

@server.tool()
def make_payment(
    invoice_id: int,
    amount: float = None,
    payment_method: str = "BANK_TRANSFER",
    reference_number: str = "",
):
    """Record payment for an invoice."""

    result = record_payment(
        invoice_id=invoice_id,
        status="PAID",
        amount=amount,
        payment_method=payment_method,
        reference_number=reference_number,
    )

    return {
        "success": True,
        "invoice_id": invoice_id,
        "amount_paid": amount,
        "result": str(result),
    }


# =========================
# REMINDERS
# =========================

@server.tool()
def send_reminder(invoice_id: int):
    """Send payment reminder for overdue invoice."""

    send_payment_reminder(invoice_id)

    return {
        "success": True,
        "invoice_id": invoice_id,
        "message": "Payment reminder sent successfully",
    }


# =========================
# FOLLOW UPS
# =========================

@server.tool()
def get_followups():
    """Get CRM follow-up history."""

    db = SessionLocal()
    try:
        followups = db.query(FollowUp).all()

        return [
            {
                "id": f.id,
                "customer_id": f.customer_id,
                "invoice_id": f.invoice_id,
                "date": str(f.followup_date),
                "contact_type": f.contact_type,
                "response_status": f.response_status,
                "subject": f.subject,
                "notes": f.notes,
            }
            for f in followups
        ]
    finally:
        db.close()


# =========================
# DASHBOARD
# =========================

@server.tool()
def get_dashboard():
    """Get CRM dashboard KPIs."""

    refresh_overdue_invoices()
    db = SessionLocal()

    try:
        quotations = db.query(Quotation).all()
        invoices = db.query(Invoice).all()
        deliveries = db.query(Delivery).all()

        won = [
            q for q in quotations
            if q.status == "WON"
        ]

        declined = [
            q for q in quotations
            if q.status == "DECLINED"
        ]

        overdue = [
            i for i in invoices
            if i.status == "OVERDUE"
        ]

        pending = [
            i for i in invoices
            if i.status in ["PENDING", "PARTIAL"]
        ]

        paid = [
            i for i in invoices
            if i.status == "PAID"
        ]

        return {
            "quotation_count": len(quotations),
            "won_quotations": len(won),
            "declined_quotations": len(declined),

            "conversion_percent": (
                round(
                    len(won) / len(quotations) * 100,
                    2
                )
                if quotations else 0
            ),

            "quotation_value": sum(
                q.total_amount or 0
                for q in quotations
            ),

            "outstanding_amount": sum(
                i.total_amount or 0
                for i in pending + overdue
            ),

            "overdue_amount": sum(
                i.total_amount or 0
                for i in overdue
            ),

            "paid_amount": sum(
                i.total_amount or 0
                for i in paid
            ),

            "pending_invoices": len(pending),
            "overdue_invoices": len(overdue),
            "paid_invoices": len(paid),

            "deliveries_in_process": len([
                d for d in deliveries
                if d.delivery_status == "IN_PROCESS"
            ]),

            "deliveries_completed": len([
                d for d in deliveries
                if d.delivery_status == "COMPLETED"
            ]),
        }

    finally:
        db.close()


# =========================
# START SERVER
# =========================

if __name__ == "__main__":
    server.run(transport="streamable-http")