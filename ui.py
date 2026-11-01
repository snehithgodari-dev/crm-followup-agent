from datetime import date
from pathlib import Path
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, send_file

app = Flask(__name__)
app.secret_key = "crm-followup-local"
API = "http://127.0.0.1:8001"
ROOT = Path(__file__).resolve().parent
QUOTATION_FOLDER = ROOT / "uploads" / "quotations"
QUOTATION_FOLDER.mkdir(parents=True, exist_ok=True)


def api_get(path):
    return requests.get(API + path, timeout=30)


def api_post(path, payload=None, files=None):
    if files:
        return requests.post(API + path, files=files, timeout=120)
    return requests.post(API + path, json=payload or {}, timeout=120)


@app.route("/")
def dashboard():
    try:
        stats = api_get("/dashboard/stats").json()
        quotations = api_get("/quotations").json().get("quotations", [])
        purchase_orders = api_get("/purchase-orders").json().get("purchase_orders", [])
    except Exception as exc:
        stats = {}
        quotations = []
        purchase_orders = []
        flash(f"FastAPI is not reachable: {exc}", "error")
    return render_template("dashboard.html", stats=stats, quotations=quotations, purchase_orders=purchase_orders)


@app.route("/quotation/new")
def quotation_new():
    return render_template("quotation_form.html", today=date.today().isoformat())


@app.route("/quotation/create", methods=["POST"])
def quotation_create():
    form = request.form
    descriptions = request.form.getlist("description[]")
    hsn_codes = request.form.getlist("hsn_code[]") or request.form.getlist("hsn[]")
    quantities = request.form.getlist("quantity[]") or request.form.getlist("qty[]")
    rates = request.form.getlist("rate[]") or request.form.getlist("unit_price[]")
    tax_rates = request.form.getlist("tax_rate[]")
    units = request.form.getlist("unit[]")

    items = []
    for i, desc in enumerate(descriptions):
        if not desc.strip():
            continue
        raw_qty = quantities[i] if i < len(quantities) else None
        if raw_qty is None or str(raw_qty).strip() == "":
            flash(f"Please enter a valid quantity for item: {desc}", "error")
            return redirect(url_for("quotation_new"))
        try:
            qty_val = float(raw_qty)
            if qty_val <= 0:
                flash(f"Quantity must be greater than 0 for item: {desc}", "error")
                return redirect(url_for("quotation_new"))
        except (ValueError, TypeError):
            flash(f"Invalid quantity '{raw_qty}' for item: {desc}", "error")
            return redirect(url_for("quotation_new"))

        raw_rate = rates[i] if i < len(rates) else None
        try:
            rate_val = float(raw_rate) if raw_rate is not None and str(raw_rate).strip() != "" else 0.0
        except (ValueError, TypeError):
            rate_val = 0.0

        raw_tax = tax_rates[i] if i < len(tax_rates) else None
        try:
            tax_val = float(raw_tax) if raw_tax is not None and str(raw_tax).strip() != "" else 18.0
        except (ValueError, TypeError):
            tax_val = 18.0

        items.append({
            "description": desc.strip(),
            "hsn_code": (hsn_codes[i] if i < len(hsn_codes) else "").strip(),
            "quantity": qty_val,
            "unit_price": rate_val,
            "tax_rate": tax_val,
            "unit": (units[i] if i < len(units) else "").strip(),
        })

    if not items:
        flash("Please add at least one valid item.", "error")
        return redirect(url_for("quotation_new"))

    payload = {
        "quotation_number": form.get("quotation_number") or None,
        "quotation_date": form.get("quotation_date") or date.today().isoformat(),
        "valid_until": None,
        "customer": {
            "company_name": form.get("customer_company") or form.get("customer_name"),
            "contact_person": form.get("customer_contact"),
            "email": form.get("customer_email"),
            "phone": form.get("customer_phone"),
            "address": form.get("customer_address"),
            "gstin": form.get("customer_gstin"),
        },
        "items": items,
    }
    try:
        r = api_post("/quotations", payload)
        data = r.json()
        if not data.get("success"):
            flash(data.get("error", "Quotation could not be saved."), "error")
            return redirect(url_for("quotation_new"))
        q = data["quotation"]
        # PDF generation is kept in a small server-side helper below.
        generate_pdf(q, form)
        return redirect(url_for("quotation_detail", quotation_id=q["id"]))
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("quotation_new"))


def generate_pdf(q, form):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    out = QUOTATION_FOLDER / f"{q['quotation_number']}.pdf"
    font = ROOT / "static" / "fonts" / "DejaVuSans.ttf"
    if font.exists():
        try:
            pdfmetrics.registerFont(TTFont("DejaVu", str(font)))
            base_font = "DejaVu"
        except Exception:
            base_font = "Helvetica"
    else:
        base_font = "Helvetica"

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallCRM", parent=styles["Normal"], fontName=base_font, fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="CenterCRM", parent=styles["Normal"], fontName=base_font, alignment=TA_CENTER, fontSize=9))
    styles.add(ParagraphStyle(name="RightCRM", parent=styles["Normal"], fontName=base_font, alignment=TA_RIGHT, fontSize=9))
    styles.add(ParagraphStyle(name="TitleCRM", parent=styles["Title"], fontName=base_font, fontSize=18, leading=22, alignment=TA_CENTER))

    doc = SimpleDocTemplate(str(out), pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    story.append(Paragraph(f"<b>{form.get('company_name') or 'PIONEER ENTERPRISES'}</b>", styles["TitleCRM"]))
    story.append(Paragraph(form.get("company_address", ""), styles["CenterCRM"]))
    story.append(Paragraph(f"GSTIN: {form.get('company_gstin', '')}", styles["CenterCRM"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>QUOTATION</b>", styles["TitleCRM"]))
    story.append(Spacer(1, 8))

    meta = [
        [Paragraph(f"<b>REF No.</b><br/>{q['quotation_number']}", styles["SmallCRM"]),
         Paragraph(f"<b>Quotation Date</b><br/>{q['quotation_date']}", styles["SmallCRM"])],
    ]
    t = Table(meta, colWidths=[260, 260])
    t.setStyle(TableStyle([("BOX", (0,0), (-1,-1), .5, colors.grey), ("INNERGRID", (0,0), (-1,-1), .25, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(t)
    story.append(Spacer(1, 10))
    customer = q.get("customer") or {}
    story.append(Paragraph("<b>BILL TO</b>", styles["SmallCRM"]))
    story.append(Paragraph(f"<b>{customer.get('company_name','')}</b><br/>{customer.get('address','')}<br/>GSTIN: {customer.get('gstin','')}<br/>Contact: {customer.get('contact_person','')} | Email: {customer.get('email','')}", styles["SmallCRM"]))
    story.append(Spacer(1, 10))

    data = [["S.No", "Item & Description", "HSN/SAC", "Qty", "Rate", "Tax", "Amount"]]
    for idx, item in enumerate(q.get("items", []), 1):
        data.append([str(idx), item.get("description", ""), item.get("hsn_code", ""), str(item.get("quantity", "")), f"₹{float(item.get('unit_price') or 0):,.2f}", f"{float(item.get('tax_rate') or 0):g}%", f"₹{float(item.get('line_total') or 0):,.2f}"])
    data += [["", "", "", "", "", "Sub Total", f"₹{q['subtotal']:,.2f}"], ["", "", "", "", "", "Tax", f"₹{q['tax_amount']:,.2f}"], ["", "", "", "", "", "Total", f"₹{q['total_amount']:,.2f}"]]
    table = Table(data, colWidths=[32, 190, 55, 40, 65, 45, 75], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), base_font), ("FONTSIZE", (0,0), (-1,-1), 8),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#eee7f8")), ("GRID", (0,0), (-1,-1), .4, colors.grey),
        ("ALIGN", (0,0), (0,-1), "CENTER"), ("ALIGN", (3,1), (-1,-1), "RIGHT"),
        ("FONTNAME", (-2,-3), (-1,-1), base_font),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Notes</b><br/>{form.get('notes','')}", styles["SmallCRM"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Terms & Conditions</b><br/>Payment: 50% advance along with PO, balance after work completion<br/>Delivery: 1 week from order with payment receiving<br/>Transportation: Included<br/>Validity: 10 days", styles["SmallCRM"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph(f"For <b>{form.get('company_name') or 'PIONEER ENTERPRISES'}</b><br/><br/>Authorized Signature", styles["RightCRM"]))
    doc.build(story)


@app.route("/quotation/<int:quotation_id>")
def quotation_detail(quotation_id):
    try:
        data = api_get(f"/quotations/{quotation_id}").json()
        if not data.get("success"):
            flash(data.get("error", "Quotation not found."), "error")
            return redirect(url_for("dashboard"))
        return render_template("quotation_detail.html", q=data["quotation"])
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.route("/quotation/<int:quotation_id>/download")
def quotation_download(quotation_id):
    try:
        data = api_get(f"/quotations/{quotation_id}").json()
        q = data.get("quotation")
        if not q:
            return redirect(url_for("dashboard"))
        path = QUOTATION_FOLDER / f"{q['quotation_number']}.pdf"
        return send_file(path, as_attachment=True, download_name=path.name)
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.post("/quotation/<int:quotation_id>/send")
def quotation_send(quotation_id):
    r = api_post(f"/quotations/{quotation_id}/send", {"email": request.form.get("email")})
    data = r.json()
    flash(data.get("message") if data.get("success") else data.get("error", "Email failed."), "success" if data.get("success") else "error")
    return redirect(url_for("quotation_detail", quotation_id=quotation_id))


@app.post("/quotation/<int:quotation_id>/accept")
def quotation_accept(quotation_id):
    r = api_post(f"/quotations/{quotation_id}/accept")
    data = r.json()
    if data.get("success"):
        return redirect(url_for("quotation_po", quotation_id=quotation_id))
    flash(data.get("error", "Could not accept quotation."), "error")
    return redirect(url_for("dashboard"))


@app.post("/quotation/<int:quotation_id>/decline")
def quotation_decline(quotation_id):
    r = api_post(f"/quotations/{quotation_id}/decline")
    data = r.json()
    flash(data.get("message") if data.get("success") else data.get("error", "Could not decline quotation."), "success" if data.get("success") else "error")
    return redirect(url_for("dashboard"))


@app.route("/quotation/<int:quotation_id>/po", methods=["GET", "POST"])
def quotation_po(quotation_id):
    if request.method == "POST":
        uploaded = request.files.get("po_file")
        if not uploaded or not uploaded.filename:
            flash("Please choose a PO PDF.", "error")
            return redirect(url_for("quotation_po", quotation_id=quotation_id))
        r = api_post(f"/quotations/{quotation_id}/po", files={"file": (uploaded.filename, uploaded.stream, uploaded.mimetype or "application/pdf")})
        data = r.json()
        if data.get("success"):
            flash("Purchase Order uploaded, processed and linked successfully.", "success")
            return redirect(url_for("quotation_workflow", quotation_id=quotation_id))
        flash(data.get("error", "PO processing failed."), "error")
    try:
        workflow = api_get(f"/quotations/{quotation_id}/workflow").json()
        if not workflow.get("success"):
            flash(workflow.get("error", "Quotation not found."), "error")
            return redirect(url_for("dashboard"))
        return render_template("purchase_order.html", **workflow)
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.route("/quotation/<int:quotation_id>/workflow")
def quotation_workflow(quotation_id):
    try:
        workflow = api_get(f"/quotations/{quotation_id}/workflow").json()
        if not workflow.get("success"):
            flash(workflow.get("error", "Workflow not found."), "error")
            return redirect(url_for("dashboard"))

        quotation = workflow.get("quotation") or {}
        purchase_order = workflow.get("purchase_order")
        delivery = workflow.get("delivery")
        invoice = workflow.get("invoice")

        if quotation.get("status") in ("NOT_ACTIVE", "DECLINED"):
            return render_template("quotation_inactive.html", **workflow)

        if not purchase_order:
            return render_template("purchase_order.html", **workflow)

        if not delivery or (delivery.get("delivery_status") or "").upper() != "COMPLETED":
            return render_template("delivery.html", **workflow)

        if not invoice:
            return render_template("invoice.html", **workflow)

        return render_template("payment.html", **workflow)
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.route("/purchase-orders")
def purchase_orders():
    try:
        data = api_get("/purchase-orders").json()
        if not data.get("success"):
            flash(data.get("error", "Could not load Purchase Orders."), "error")
            return redirect(url_for("dashboard"))
        return render_template("purchase_orders.html", purchase_orders=data.get("purchase_orders", []))
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.route("/overdue-invoices")
def overdue_invoices():
    try:
        data = api_get("/invoices/overdue").json()
        if not data.get("success"):
            flash(data.get("error", "Could not load overdue invoices."), "error")
            return redirect(url_for("dashboard"))
        return render_template(
            "overdue_invoices.html",
            invoices=data.get("invoices", []),
        )
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.route("/purchase-order/<int:po_id>")
def purchase_order_detail(po_id):
    try:
        workflow = api_get(f"/purchase-orders/{po_id}/workflow").json()
        if not workflow.get("success"):
            flash(workflow.get("error", "Purchase Order not found."), "error")
            return redirect(url_for("dashboard"))
        return render_template("purchase_order_detail.html", **workflow)
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))


@app.post("/purchase-order/<int:po_id>/delivery")
def delivery_update(po_id):
    status = request.form.get("status", "NOT_STARTED")
    quotation_id = request.form.get("quotation_id")
    payload = {
        "status": status,
        "remarks": request.form.get("remarks"),
        "expected_date": request.form.get("expected_date") or None,
    }
    r = api_post(f"/purchase-orders/{po_id}/delivery", payload)
    data = r.json()
    if data.get("success"):
        target_qid = quotation_id or data.get("quotation_id")
        if target_qid:
            return redirect(url_for("quotation_workflow", quotation_id=int(target_qid)))
        # Safe fallback by scanning current quotations
        rows = api_get("/quotations").json().get("quotations", [])
        for q in rows:
            wf = api_get(f"/quotations/{q['id']}/workflow").json()
            po_data = wf.get("purchase_order")
            if po_data and po_data.get("id") == po_id:
                return redirect(url_for("quotation_workflow", quotation_id=q["id"]))
        flash("Delivery updated.", "success")
        return redirect(url_for("dashboard"))
    flash(data.get("error", "Delivery update failed."), "error")
    if quotation_id:
        return redirect(url_for("quotation_workflow", quotation_id=int(quotation_id)))
    return redirect(url_for("dashboard"))


@app.post("/purchase-order/<int:po_id>/invoice")
def invoice_upload(po_id):
    quotation_id = request.form.get("quotation_id")
    uploaded = request.files.get("invoice_file")
    if not uploaded or not uploaded.filename:
        flash("Please choose an Invoice PDF.", "error")
        if quotation_id:
            return redirect(url_for("quotation_workflow", quotation_id=int(quotation_id)))
        return redirect(url_for("dashboard"))
    try:
        r = api_post(
            f"/purchase-orders/{po_id}/invoice",
            files={"file": (uploaded.filename, uploaded.stream, uploaded.mimetype or "application/pdf")},
        )
        data = r.json()
        if data.get("success"):
            flash("Invoice uploaded, processed and saved successfully.", "success")
        else:
            flash(data.get("error", "Invoice processing failed."), "error")
    except Exception as exc:
        flash(str(exc), "error")

    if quotation_id:
        return redirect(url_for("quotation_workflow", quotation_id=int(quotation_id)))
    return redirect(url_for("dashboard"))


@app.post("/invoice/<int:invoice_id>/payment")
def payment_record(invoice_id):
    quotation_id = request.form.get("quotation_id")
    status = request.form.get("status", "PAID")
    payload = {
        "status": status,
        "amount": request.form.get("amount") or None,
        "payment_method": request.form.get("payment_method") or "BANK_TRANSFER",
        "reference_number": request.form.get("reference_number") or None,
        "notes": request.form.get("notes") or None,
    }
    try:
        r = api_post(f"/invoices/{invoice_id}/payment", payload)
        data = r.json()
        if data.get("success"):
            flash(f"Payment status recorded: {status}.", "success")
        else:
            flash(data.get("error", "Payment recording failed."), "error")
    except Exception as exc:
        flash(str(exc), "error")

    if quotation_id:
        return redirect(url_for("quotation_workflow", quotation_id=int(quotation_id)))
    return redirect(url_for("dashboard"))


@app.post("/invoice/<int:invoice_id>/reminder")
def reminder_send(invoice_id):
    quotation_id = request.form.get("quotation_id")
    try:
        r = api_post(f"/invoices/{invoice_id}/reminder")
        data = r.json()
        if data.get("success"):
            flash("Payment reminder email sent successfully.", "success")
        else:
            flash(data.get("error", "Reminder sending failed."), "error")
    except Exception as exc:
        flash(str(exc), "error")

    if quotation_id:
        return redirect(url_for("quotation_workflow", quotation_id=int(quotation_id)))
    return redirect(url_for("dashboard"))


@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")


@app.post("/chat")
def chat():
    if request.is_json:
        req_data = request.get_json() or {}
        message = (req_data.get("message") or "").strip()
        try:
            r = api_post("/chat", {"message": message})
            data = r.json()
            return data
        except Exception as exc:
            return {"success": False, "error": str(exc)}, 500

    message = request.form.get("message", "").strip()
    try:
        r = api_post("/chat", {"message": message})
        data = r.json()
        response = data.get("response") or data.get("error", "No response")
    except Exception as exc:
        response = str(exc)
    return render_template("chatbot.html", message=message, response=response)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
