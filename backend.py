import asyncio
import os
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from database.db import SessionLocal
from database.models import (
    Customer, Quotation, QuotationItem, PurchaseOrder, Delivery,
    Invoice, Payment, Document
)
from services.payment_service import refresh_overdue_invoices

load_dotenv()

APP_ROOT = Path(__file__).resolve().parent
UPLOAD_ROOT = APP_ROOT / "uploads"
QUOTATION_ROOT = UPLOAD_ROOT / "quotations"
PO_ROOT = UPLOAD_ROOT / "purchase_orders"
INVOICE_ROOT = UPLOAD_ROOT / "invoices"
for p in (QUOTATION_ROOT, PO_ROOT, INVOICE_ROOT):
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CRM Follow-Up Portal API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def serialize_customer(c):
    if not c:
        return None
    return {
        "id": c.id,
        "company_name": c.company_name,
        "contact_person": c.contact_person,
        "email": c.email,
        "phone": c.phone,
        "address": c.address,
        "gstin": c.gstin,
        "pan": c.pan,
    }


def serialize_quotation(q):
    po = q.purchase_order
    return {
        "id": q.id,
        "quotation_number": q.quotation_number,
        "customer_id": q.customer_id,
        "customer": serialize_customer(q.customer),
        "quotation_date": q.quotation_date.isoformat() if q.quotation_date else None,
        "valid_until": q.valid_until.isoformat() if q.valid_until else None,
        "subtotal": q.subtotal or 0,
        "tax_amount": q.tax_amount or 0,
        "total_amount": q.total_amount or 0,
        "status": q.status,
        "has_po": bool(po),
        "po_id": po.id if po else None,
        "po_number": po.po_number if po else None,
        "items": [
            {
                "id": i.id,
                "item_code": i.item_code,
                "description": i.description,
                "hsn_code": i.hsn_code,
                "quantity": i.quantity,
                "unit": i.unit,
                "unit_price": i.unit_price,
                "tax_rate": i.tax_rate,
                "line_total": i.line_total,
            }
            for i in q.items
        ],
    }


def serialize_po(po):
    if not po:
        return None
    return {
        "id": po.id,
        "quotation_id": po.quotation_id,
        "customer_id": po.customer_id,
        "po_number": po.po_number,
        "po_date": po.po_date.isoformat() if po.po_date else None,
        "subtotal": po.subtotal or 0,
        "tax_amount": po.tax_amount or 0,
        "total_amount": po.total_amount or 0,
        "payment_terms": po.payment_terms,
        "payment_days": po.payment_days,
        "delivery_terms": po.delivery_terms,
        "delivery_date": po.delivery_date.isoformat() if po.delivery_date else None,
        "buyer_name": po.buyer_name,
        "buyer_email": po.buyer_email,
        "buyer_phone": po.buyer_phone,
        "status": po.status,
    }


def serialize_delivery(d):
    if not d:
        return None
    return {
        "id": d.id,
        "purchase_order_id": d.purchase_order_id,
        "delivery_status": d.delivery_status,
        "expected_date": d.expected_date.isoformat() if d.expected_date else None,
        "actual_date": d.actual_date.isoformat() if d.actual_date else None,
        "remarks": d.remarks,
    }


def serialize_invoice(inv):
    if not inv:
        return None

    total_paid = sum(
        float(p.amount or 0)
        for p in (inv.payments or [])
        if p.status in ("PAID", "PARTIAL")
    )
    total_amount = float(inv.total_amount or 0)

    return {
        "id": inv.id,
        "purchase_order_id": inv.purchase_order_id,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "remaining_amount": max(total_amount - total_paid, 0.0),
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "status": inv.status,
        "payment_terms": inv.payment_terms,
    }


def serialize_payment(p):
    if not p:
        return None
    return {
        "id": p.id,
        "invoice_id": p.invoice_id,
        "amount": p.amount,
        "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        "payment_method": p.payment_method,
        "reference_number": p.reference_number,
        "status": p.status,
        "notes": p.notes,
    }


def next_quotation_number(db):
    year = datetime.now().year
    prefix = f"Q-{year}-"
    rows = db.query(Quotation).filter(Quotation.quotation_number.like(f"{prefix}%")).all()
    nums = []
    for q in rows:
        try:
            nums.append(int(q.quotation_number.split("-")[-1]))
        except Exception:
            pass
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


def send_email_with_attachment(to_email, subject, body, attachment_path):
    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_APP_PASSWORD")
    if not sender or not password:
        raise RuntimeError("EMAIL_ADDRESS or EMAIL_APP_PASSWORD is missing in .env")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with open(attachment_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=Path(attachment_path).name)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(msg)


@app.get("/")
def root():
    return {"message": "CRM Follow-Up Portal API", "status": "running"}


@app.get("/dashboard/stats")
def dashboard_stats():
    refresh_overdue_invoices()
    db = SessionLocal()
    try:
        quotations = db.query(Quotation).count()
        purchase_orders = db.query(PurchaseOrder).count()
        pending_po = db.query(Quotation).filter(Quotation.status.in_(["AWAITING_PO", "ACCEPTED"])).count()
        deliveries = db.query(Delivery).count()
        deliveries_in_process = db.query(Delivery).filter(Delivery.delivery_status == "IN_PROCESS").count()
        deliveries_completed = db.query(Delivery).filter(Delivery.delivery_status == "COMPLETED").count()
        invoices = db.query(Invoice).count()
        pending_payments = db.query(Invoice).filter(Invoice.status.in_(["PENDING", "PARTIAL"])).count()
        overdue = db.query(Invoice).filter(Invoice.status == "OVERDUE").count()
        paid_invoices = db.query(Invoice).filter(Invoice.status == "PAID").count()
        payments = db.query(Payment).count()
        return {
            "quotations": quotations,
            "total_quotations": quotations,
            "awaiting_po": pending_po,
            "pending_po": pending_po,
            "purchase_orders": purchase_orders,
            "deliveries": deliveries,
            "deliveries_in_process": deliveries_in_process,
            "deliveries_completed": deliveries_completed,
            "invoices": invoices,
            "pending_payments": pending_payments,
            "overdue": overdue,
            "overdue_invoices": overdue,
            "paid_invoices": paid_invoices,
            "payments": payments,
        }
    finally:
        db.close()


@app.get("/quotations")
def get_quotations():
    db = SessionLocal()
    try:
        rows = db.query(Quotation).order_by(Quotation.id.desc()).all()
        return {"quotations": [serialize_quotation(q) for q in rows]}
    finally:
        db.close()


@app.post("/quotations")
def create_quotation(data: dict):
    db = SessionLocal()
    try:
        customer_data = data.get("customer", {})
        email = (customer_data.get("email") or "").strip()
        company = (customer_data.get("company_name") or customer_data.get("name") or "").strip()
        if not company:
            return {"success": False, "error": "Customer/company name is required."}

        customer = None
        if email:
            customer = db.query(Customer).filter(Customer.email == email).first()
        if not customer:
            customer = db.query(Customer).filter(Customer.company_name == company).first()
        if not customer:
            customer = Customer(
                company_name=company,
                contact_person=customer_data.get("contact_person"),
                email=email,
                phone=customer_data.get("phone"),
                address=customer_data.get("address"),
                gstin=customer_data.get("gstin"),
                pan=customer_data.get("pan"),
            )
            db.add(customer)
            db.flush()

        items = data.get("items") or []
        subtotal = 0.0
        tax = 0.0
        clean_items = []
        for item in items:
            raw_qty = item.get("quantity") if item.get("quantity") is not None else item.get("qty")
            try:
                qty = float(raw_qty) if raw_qty is not None and str(raw_qty).strip() != "" else 0.0
            except (ValueError, TypeError):
                qty = 0.0

            raw_rate = item.get("unit_price") if item.get("unit_price") is not None else item.get("rate")
            try:
                rate = float(raw_rate) if raw_rate is not None and str(raw_rate).strip() != "" else 0.0
            except (ValueError, TypeError):
                rate = 0.0

            raw_tax = item.get("tax_rate")
            try:
                tax_rate = float(raw_tax) if raw_tax is not None and str(raw_tax).strip() != "" else 0.0
            except (ValueError, TypeError):
                tax_rate = 0.0

            line = qty * rate
            line_tax = line * tax_rate / 100
            subtotal += line
            tax += line_tax
            clean_items.append((item, qty, rate, tax_rate, line + line_tax))

        q = Quotation(
            quotation_number=next_quotation_number(db),
            customer_id=customer.id,
            quotation_date=date.fromisoformat(data.get("quotation_date")) if data.get("quotation_date") else date.today(),
            valid_until=date.fromisoformat(data.get("valid_until")) if data.get("valid_until") else None,
            subtotal=subtotal,
            tax_amount=tax,
            total_amount=subtotal + tax,
            status="DRAFT",
        )
        db.add(q)
        db.flush()
        for item, qty, rate, tax_rate, total in clean_items:
            db.add(QuotationItem(
                quotation_id=q.id,
                item_code=item.get("item_code"),
                description=item.get("description") or item.get("item"),
                hsn_code=item.get("hsn_code"),
                quantity=qty,
                unit=item.get("unit"),
                unit_price=rate,
                tax_rate=tax_rate,
                line_total=total,
            ))
        db.commit()
        db.refresh(q)
        return {"success": True, "quotation": serialize_quotation(q)}
    except Exception as exc:
        db.rollback()
        return {"success": False, "error": f"Quotation save failed: {exc}"}
    finally:
        db.close()


@app.get("/quotations/{quotation_id}")
def get_quotation(quotation_id: int):
    db = SessionLocal()
    try:
        q = db.query(Quotation).filter(Quotation.id == quotation_id).first()
        if not q:
            return {"success": False, "error": "Quotation not found."}
        return {"success": True, "quotation": serialize_quotation(q)}
    finally:
        db.close()


@app.post("/quotations/{quotation_id}/send")
def send_quotation(quotation_id: int, data: dict):
    db = SessionLocal()
    try:
        q = db.query(Quotation).filter(Quotation.id == quotation_id).first()
        if not q:
            return {"success": False, "error": "Quotation not found."}
        to_email = (data.get("email") or q.customer.email or "").strip()
        if not to_email:
            return {"success": False, "error": "Customer email is required."}
        pdf = QUOTATION_ROOT / f"{q.quotation_number}.pdf"
        if not pdf.exists():
            return {"success": False, "error": "Quotation PDF not found. Recreate the quotation document first."}
        send_email_with_attachment(
            to_email,
            f"Quotation {q.quotation_number}",
            f"Dear {q.customer.company_name},\n\nPlease find quotation {q.quotation_number} attached.\n\nRegards,\nCRM Follow-Up Portal",
            pdf,
        )
        q.status = "SENT"
        q.sent_at = datetime.utcnow()
        db.commit()
        return {"success": True, "message": f"Quotation {q.quotation_number} sent to {to_email}."}
    except Exception as exc:
        db.rollback()
        return {"success": False, "error": str(exc)}
    finally:
        db.close()


@app.post("/quotations/{quotation_id}/accept")
def accept_quotation(quotation_id: int):
    db = SessionLocal()
    try:
        q = db.query(Quotation).filter(Quotation.id == quotation_id).first()
        if not q:
            return {"success": False, "error": "Quotation not found."}
        if q.status not in ("SENT", "DRAFT"):
            return {"success": False, "error": f"Quotation is currently {q.status}."}
        q.status = "AWAITING_PO"
        q.accepted_at = datetime.utcnow()
        db.commit()
        return {"success": True, "message": "Quotation accepted. Purchase Order is now required."}
    finally:
        db.close()



@app.post("/quotations/{quotation_id}/decline")
def decline_quotation(quotation_id: int):
    db = SessionLocal()

    try:
        q = (
            db.query(Quotation)
            .filter(Quotation.id == quotation_id)
            .first()
        )

        if not q:
            return {
                "success": False,
                "error": "Quotation not found."
            }

        if q.status in ("WON", "AWAITING_PO"):
            return {
                "success": False,
                "error": "This quotation has already been accepted and cannot be declined."
            }

        q.status = "NOT_ACTIVE"
        q.declined_at = datetime.utcnow()

        db.commit()

        return {
            "success": True,
            "message": "Quotation declined. Status changed to NOT ACTIVE."
        }

    except Exception as exc:
        db.rollback()

        return {
            "success": False,
            "error": str(exc)
        }

    finally:
        db.close()

@app.get("/purchase-orders")
def get_purchase_orders():
    refresh_overdue_invoices()
    db = SessionLocal()
    try:
        rows = db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc()).all()
        result = []
        for po in rows:
            delivery = db.query(Delivery).filter(Delivery.purchase_order_id == po.id).order_by(Delivery.id.desc()).first()
            invoice = db.query(Invoice).filter(Invoice.purchase_order_id == po.id).order_by(Invoice.id.desc()).first()
            result.append({
                **serialize_po(po),
                "quotation_number": po.quotation.quotation_number if po.quotation else None,
                "customer": serialize_customer(po.customer),
                "delivery_status": delivery.delivery_status if delivery else "NOT_STARTED",
                "invoice_number": invoice.invoice_number if invoice else None,
                "invoice_status": invoice.status if invoice else None,
            })
        return {"success": True, "purchase_orders": result}
    finally:
        db.close()


@app.get("/purchase-orders/{po_id}/workflow")
def purchase_order_workflow(po_id: int):
    refresh_overdue_invoices()
    db = SessionLocal()
    try:
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            return {"success": False, "error": "Purchase Order not found."}
        delivery = db.query(Delivery).filter(Delivery.purchase_order_id == po_id).order_by(Delivery.id.desc()).first()
        invoice = db.query(Invoice).filter(Invoice.purchase_order_id == po_id).order_by(Invoice.id.desc()).first()
        payment = db.query(Payment).filter(Payment.invoice_id == invoice.id).order_by(Payment.id.desc()).first() if invoice else None
        return {
            "success": True,
            "quotation": serialize_quotation(po.quotation) if po.quotation else None,
            "purchase_order": serialize_po(po),
            "delivery": serialize_delivery(delivery),
            "invoice": serialize_invoice(invoice),
            "payment": serialize_payment(payment),
        }
    finally:
        db.close()


@app.get("/quotations/{quotation_id}/workflow")
def quotation_workflow(quotation_id: int):
    refresh_overdue_invoices()
    db = SessionLocal()
    try:
        q = db.query(Quotation).filter(Quotation.id == quotation_id).first()
        if not q:
            return {"success": False, "error": "Quotation not found."}
        po = db.query(PurchaseOrder).filter(PurchaseOrder.quotation_id == quotation_id).first()
        delivery = db.query(Delivery).filter(Delivery.purchase_order_id == po.id).order_by(Delivery.id.desc()).first() if po else None
        invoice = db.query(Invoice).filter(Invoice.purchase_order_id == po.id).order_by(Invoice.id.desc()).first() if po else None
        payment = db.query(Payment).filter(Payment.invoice_id == invoice.id).order_by(Payment.id.desc()).first() if invoice else None
        return {
            "success": True,
            "quotation": serialize_quotation(q),
            "purchase_order": serialize_po(po),
            "delivery": serialize_delivery(delivery),
            "invoice": serialize_invoice(invoice),
            "payment": serialize_payment(payment),
        }
    finally:
        db.close()


@app.post("/quotations/{quotation_id}/po")
async def upload_po(quotation_id: int, file: UploadFile = File(...)):
    db = SessionLocal()
    try:
        q = db.query(Quotation).filter(Quotation.id == quotation_id).first()
        if not q:
            return {"success": False, "error": "Quotation not found."}
        if q.status not in ("ACCEPTED", "AWAITING_PO", "WON"):
            return {
        "success": False,
        "error": "PO upload is allowed only after quotation acceptance."
    }
    finally:
        db.close()

    safe_name = Path(file.filename or "purchase_order.pdf").name
    file_path = PO_ROOT / safe_name
    with open(file_path, "wb") as f:
        f.write(await file.read())

    try:
        from services.po_upload_service import upload_po_for_quotation
        result = await asyncio.to_thread(upload_po_for_quotation, quotation_id, str(file_path))
        if not result.get("success"):
            err_msg = (
                result.get("errors", ["PO processing failed."])[0]
                if isinstance(result.get("errors"), list) and result.get("errors")
                else result.get("error", "PO processing failed.")
            )
            return {"success": False, "error": err_msg, "result": result}
        return {"success": True, "message": "Purchase Order processed and linked to the quotation.", "result": result}
    except Exception as exc:
        return {"success": False, "error": f"PO processing failed: {exc}"}


@app.post("/purchase-orders/{po_id}/delivery")
def update_delivery(po_id: int, data: dict):
    db = SessionLocal()
    try:
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            return {"success": False, "error": "Purchase Order not found."}
        delivery = db.query(Delivery).filter(Delivery.purchase_order_id == po_id).order_by(Delivery.id.desc()).first()
        if not delivery:
            delivery = Delivery(purchase_order_id=po_id, delivery_status="NOT_STARTED")
            db.add(delivery)
        status = (data.get("status") or "NOT_STARTED").upper()
        if status not in {"NOT_STARTED", "IN_PROCESS", "COMPLETED"}:
            return {"success": False, "error": "Invalid delivery status."}

        if delivery.delivery_status == "COMPLETED" and status != "COMPLETED":
            return {
                "success": False,
                "error": (
                    "Delivery is already COMPLETED and cannot be moved "
                    "back to another status."
                ),
            }

        delivery.delivery_status = status
        delivery.remarks = data.get("remarks")
        if data.get("expected_date"):
            delivery.expected_date = date.fromisoformat(data["expected_date"])
        delivery.actual_date = date.today() if status == "COMPLETED" else None
        db.commit()
        return {"success": True, "delivery": serialize_delivery(delivery), "quotation_id": po.quotation_id}
    except Exception as exc:
        db.rollback()
        return {"success": False, "error": str(exc)}
    finally:
        db.close()


@app.post("/purchase-orders/{po_id}/invoice")
async def upload_invoice(po_id: int, file: UploadFile = File(...)):
    db = SessionLocal()
    try:
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            return {"success": False, "error": "Purchase Order not found."}
        delivery = db.query(Delivery).filter(Delivery.purchase_order_id == po_id).order_by(Delivery.id.desc()).first()
        if not delivery or delivery.delivery_status != "COMPLETED":
            return {"success": False, "error": "Invoice upload requires completed delivery."}
    finally:
        db.close()

    safe_name = Path(file.filename or "invoice.pdf").name
    file_path = INVOICE_ROOT / safe_name
    with open(file_path, "wb") as f:
        f.write(await file.read())

    try:
        from services.invoice_upload_service import upload_invoice_for_po
        result = await asyncio.to_thread(upload_invoice_for_po, po_id, str(file_path))
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "Invoice processing failed.")}
        return {"success": True, "message": "Invoice processed and linked successfully.", "result": result}
    except Exception as exc:
        return {"success": False, "error": f"Invoice processing failed: {exc}"}


@app.post("/invoices/{invoice_id}/payment")
def record_invoice_payment(invoice_id: int, data: dict):
    try:
        from services.payment_service import record_payment
        status = data.get("status", "PAID")
        amount = data.get("amount")
        payment_method = data.get("payment_method", "BANK_TRANSFER")
        reference_number = data.get("reference_number")
        notes = data.get("notes")
        result = record_payment(
            invoice_id=invoice_id,
            status=status,
            amount=amount,
            payment_method=payment_method,
            reference_number=reference_number,
            notes=notes,
        )
        return {"success": True, "result": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/invoices/{invoice_id}/reminder")
def send_invoice_reminder(invoice_id: int):
    try:
        from services.reminder_service import send_payment_reminder
        send_payment_reminder(invoice_id)
        return {"success": True, "message": "Payment reminder email sent successfully."}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/invoices/overdue")
def get_overdue_invoice_list():
    refresh_overdue_invoices()
    db = SessionLocal()
    try:
        invoices = (
            db.query(Invoice)
            .filter(Invoice.status == "OVERDUE")
            .order_by(Invoice.due_date.asc(), Invoice.id.asc())
            .all()
        )
        return {
            "success": True,
            "invoices": [
                {
                    **serialize_invoice(invoice),
                    "customer": serialize_customer(invoice.customer),
                    "po_number": (
                        invoice.purchase_order.po_number
                        if invoice.purchase_order
                        else None
                    ),
                }
                for invoice in invoices
            ],
        }
    finally:
        db.close()


@app.get("/documents/quotation/{quotation_id}")
def quotation_document(quotation_id: int):
    db = SessionLocal()
    try:
        q = db.query(Quotation).filter(Quotation.id == quotation_id).first()
        if not q:
            return {"success": False, "error": "Quotation not found."}
        path = QUOTATION_ROOT / f"{q.quotation_number}.pdf"
        if not path.exists():
            return {"success": False, "error": "Quotation PDF not found."}
        return FileResponse(path, media_type="application/pdf", filename=path.name)
    finally:
        db.close()


@app.post("/chat")
async def chat(data: dict):
    message = (data.get("message") or "").strip()
    if not message:
        return {"success": False, "error": "Please enter a message."}
    try:
        from agent import run_agent
        answer = await asyncio.to_thread(run_agent, message)
        return {"success": True, "response": answer}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="127.0.0.1", port=8001, reload=False)
