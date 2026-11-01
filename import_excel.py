import pandas as pd

from db import get_connection, init_db


EXCEL_FILE = "sample.xlsx"


def import_excel():

    # Make sure the database and tables exist
    init_db()

    # Read Excel file
    df = pd.read_excel(EXCEL_FILE)

    # Clean Excel column names
    # Example:
    # "Customer ID" -> "customer id"
    # "status "     -> "status"
    df.columns = df.columns.str.strip().str.lower()

    print("Excel columns:")
    print(df.columns.tolist())

    # Connect to SQLite
    conn = get_connection()

    # Process each Excel row
    for _, row in df.iterrows():

        # -------------------------
        # Customer information
        # -------------------------

        customer_id = str(row["customer id"]).strip()

        company_name = str(
            row["company name"]
        ).strip()

        contact_name = str(
            row["contact name"]
        ).strip()

        email = str(
            row["email"]
        ).strip()

        phone = str(
            row["phone"]
        ).strip()

        # -------------------------
        # Invoice information
        # -------------------------

        total = float(row["total"])

        delivery_status = str(
            row["delivery status"]
        ).strip().lower()

        # Convert date from Excel
        # DD-MM-YYYY -> YYYY-MM-DD
        payment_date = pd.to_datetime(
            row["payment date"],
            dayfirst=True
        ).strftime("%Y-%m-%d")

        # Read payment status
        # Blank Excel cell -> ""
        if pd.isna(row["status"]):
            payment_status = ""
        else:
            payment_status = str(
                row["status"]
            ).strip().lower()

        # Temporary invoice ID
        # We will replace this with the real
        # invoice number when available.
        invoice_id = f"{customer_id}-{payment_date}"

        # -------------------------
        # Insert / update customer
        # -------------------------

        conn.execute(
            """
            INSERT INTO customers
            (
                customer_id,
                company_name,
                contact_name,
                email,
                phone,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)

            ON CONFLICT(customer_id)
            DO UPDATE SET
                company_name = excluded.company_name,
                contact_name = excluded.contact_name,
                email = excluded.email,
                phone = excluded.phone
            """,
            (
                customer_id,
                company_name,
                contact_name,
                email,
                phone,
                "active",
            ),
        )

        # -------------------------
        # Insert / update invoice
        # -------------------------

        conn.execute(
            """
            INSERT INTO invoices
            (
                invoice_id,
                customer_id,
                total,
                delivery_status,
                payment_promised_date,
                payment_status,
                reminder_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(invoice_id)
            DO UPDATE SET
                total = excluded.total,
                delivery_status = excluded.delivery_status,
                payment_promised_date = excluded.payment_promised_date,
                payment_status = excluded.payment_status
            """,
            (
                invoice_id,
                customer_id,
                total,
                delivery_status,
                payment_date,
                payment_status,
                "not_sent",
            ),
        )

    # Save all changes
    conn.commit()

    # Close database connection
    conn.close()

    print()
    print("Excel data imported successfully.")


if __name__ == "__main__":
    import_excel()