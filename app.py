import streamlit as st
import pandas as pd
import sqlite3
import os
import tempfile
import json
import google.generativeai as genai
from io import BytesIO
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase
import av
import cv2
import numpy as np

# Gemini Configuration
genai.configure(api_key="AIzaSyCpujkcZAcvudbJlxGkHSmVXc5hePVxuSE")
model = genai.GenerativeModel('gemini-2.5-pro-preview-06-05')

# SQLite setup
DB_PATH = "receipts.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS receipt_items (
            company_name TEXT,
            date TEXT,
            description TEXT,
            quantity REAL,
            unit_price REAL,
            total_price REAL,
            total_before_tax REAL,
            taxes REAL,
            total_after_tax REAL
        )
    ''')
    conn.commit()
    conn.close()

def insert_items_to_db(items):
    conn = sqlite3.connect(DB_PATH)
    for item in items:
        conn.execute('''
            INSERT INTO receipt_items (
                company_name, date, description, quantity,
                unit_price, total_price, total_before_tax, taxes, total_after_tax
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            item.get("company_name"),
            item.get("date"),
            item.get("description"),
            item.get("quantity"),
            item.get("unit_price"),
            item.get("total_price"),
            item.get("total_before_tax"),
            item.get("taxes"),
            item.get("total_after_tax")
        ))
    conn.commit()
    conn.close()

def extract_receipt_data(file_path):
    uploaded_file = genai.upload_file(path=file_path)

    prompt_parts = [
        f"The file '{os.path.basename(file_path)}' may contain one or more receipts or invoices.",
        "Your task is to extract detailed structured data from each receipt or invoice found in the document.",
        "",
        "For **each** receipt or invoice, extract the following fields:",
        "- `company_name`: The name of the business issuing the receipt or invoice.",
        "- `date`: The date the receipt or invoice was issued. Format it as `YYYY-MM-DD`.",
        "- `items`: A list of purchased items, each with the following:",
        "    - `description`: Name or description of the item",
        "    - `quantity`: Number of units",
        "    - `unit_price`: Price per unit",
        "    - `total_price`: Total price for this item (as written, do not calculate)",
        "- `taxes`: Any applicable taxes such as GST (if present)",
        "- `total_before_tax`: Subtotal before tax",
        "- `total_after_tax`: Total after including tax",
        "",
        "Return the results as a **JSON array** of receipt objects. Each object should follow this structure:",
        "",
        "```json",
        "{",
        '  "company_name": "string",',
        '  "date": "YYYY-MM-DD",',
        '  "total_before_tax": number_or_string,',
        '  "taxes": number_or_string,',
        '  "total_after_tax": number_or_string,',
        '  "items": [',
        "    {",
        '      "description": "string",',
        '      "quantity": number_or_string,',
        '      "unit_price": number_or_string,',
        '      "total_price": number_or_string',
        "    }, ...",
        "  ]",
        "}",
        "```",
        "",
        "Avoid performing calculations. Just extract the values as they appear in the document.",
        "",
        uploaded_file
    ]


    response = model.generate_content(prompt_parts)
    try:
        text = response.text
        if "```json" in text:
            text = text.split("```json")[-1]
        if "```" in text:
            text = text.split("```")[0]
        data = json.loads(text.strip())
        receipts = data if isinstance(data, list) else [data]
        extracted_items = []
        for receipt in receipts:
            for item in receipt.get("items", []):
                if item.get("quantity", 0) != 0:
                    item["company_name"] = receipt.get("company_name")
                    item["date"] = receipt.get("date")
                    item["total_before_tax"] = receipt.get("total_before_tax")
                    item["taxes"] = receipt.get("taxes")
                    item["total_after_tax"] = receipt.get("total_after_tax")
                    extracted_items.append(item)
        return extracted_items
    except Exception as e:
        st.error(f"Failed to parse Gemini response: {e}")
        return []


st.title("Receipt Parser")
st.markdown("""
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

init_db()

# TESTING manually added data
st.markdown("### Manually Add Receipt Entry")
with st.form("manual_entry_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        company_name = st.text_input("Company Name")
        date = st.date_input("Date")
    with col2:
        description = st.text_input("Item Description")
        quantity = st.number_input("Quantity", min_value=0.0, step=1.0)
    with col3:
        unit_price = st.number_input("Unit Price", min_value=0.0, step=0.01)
        total_price = st.number_input("Total Price", min_value=0.0, step=0.01)

    col4, col5, col6 = st.columns(3)
    with col4:
        total_before_tax = st.number_input("Total Before Tax", min_value=0.0, step=0.01)
    with col5:
        taxes = st.number_input("Taxes (GST)", min_value=0.0, step=0.01)
    with col6:
        total_after_tax = st.number_input("Total After Tax", min_value=0.0, step=0.01)

    submitted = st.form_submit_button("Add to Database")

    if submitted:
        item = {
            "company_name": company_name,
            "date": date.strftime("%Y-%m-%d"),
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": total_price,
            "total_before_tax": total_before_tax,
            "taxes": taxes,
            "total_after_tax": total_after_tax
        }

        insert_items_to_db([item])
        st.success(f"Item '{description}' added successfully.")

# Upload Section
uploaded_files = st.file_uploader("Upload receipt files (PDF, JPG, PNG)", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    if st.button("Process Uploaded Receipts"):
        for file in uploaded_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.name)[1]) as tmp_file:
                tmp_file.write(file.read())
                tmp_path = tmp_file.name
            with st.spinner(f"Processing {file.name}..."):
                items = extract_receipt_data(tmp_path)
                insert_items_to_db(items)
                st.success(f"Processed and saved items from {file.name}")
            os.unlink(tmp_path)

st.markdown("### Capture Receipt Photo")

class VideoProcessor(VideoProcessorBase):
    def __init__(self):
        self.frame = None
        self.capture = False

    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        img = frame.to_ndarray(format="bgr24")
        if self.capture:
            self.frame = img.copy()
            self.capture = False
        return av.VideoFrame.from_ndarray(img, format="bgr24")

ctx = webrtc_streamer(
    key="receipt_camera",
    video_processor_factory=VideoProcessor,
    media_stream_constraints={"video": True, "audio": False},
)

if ctx.video_processor:
    if st.button("Capture Photo"):
        ctx.video_processor.capture = True

    if ctx.video_processor.frame is not None:
        st.image(ctx.video_processor.frame, caption="Captured Image")

        if st.button("Process Captured Image"):
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
                cv2.imwrite(tmp_file.name, ctx.video_processor.frame)
                st.success("Processing captured image...")
                items = extract_receipt_data(tmp_file.name)
                insert_items_to_db(items)
                st.success("Receipt data saved.")

st.markdown("### Latest Receipt Entries")
if st.checkbox("Show latest entries in database"):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM receipt_items ORDER BY date DESC LIMIT 50", conn)
    conn.close()
    st.dataframe(df)

# TESTING delete 
st.markdown("---")
st.subheader("Delete Receipt Entry")
conn = sqlite3.connect(DB_PATH)
df_all = pd.read_sql_query("SELECT rowid, * FROM receipt_items ORDER BY date DESC", conn)
conn.close()

if not df_all.empty:
    df_all['label'] = df_all.apply(
        lambda row: f"{row['date']} | {row['company_name']} | {row['description']} | ${row['total_price']}", axis=1
    )

    to_delete = st.multiselect(
        "Select entries to delete:",
        options=df_all['label'],
        default=[],
        key="delete_selector"
    )

    if st.button("Delete Selected Entries"):
        delete_ids = df_all[df_all['label'].isin(to_delete)]['rowid'].tolist()
        if delete_ids:
            conn = sqlite3.connect(DB_PATH)
            conn.executemany("DELETE FROM receipt_items WHERE rowid = ?", [(i,) for i in delete_ids])
            conn.commit()
            conn.close()
            st.success(f"Deleted {len(delete_ids)} entry(ies). Please refresh or rerun to see updates.")
        else:
            st.warning("No valid entries selected for deletion.")
else:
    st.info("No entries available to delete.")

# Search Section
st.markdown("---")
st.markdown("### Search Items by Description and/or Date")
col1, col2 = st.columns(2)
with col1:
    search_item = st.text_input("Search by item description:", key="search_item")
with col2:
    search_date = st.text_input("Search by date (YYYY-MM-DD):", key="search_date")

query = "SELECT * FROM receipt_items WHERE 1=1"
params = []

if search_item:
    query += " AND description LIKE ?"
    params.append(f"%{search_item}%")
if search_date:
    query += " AND date = ?"
    params.append(search_date)

if search_item or search_date:
    conn = sqlite3.connect(DB_PATH)
    results = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not results.empty:
        st.dataframe(results)
    else:
        st.write("No matching results.")

# Summary Statistics
st.markdown("---")
st.subheader("Summary Statistics")
conn = sqlite3.connect(DB_PATH)
df_summary = pd.read_sql_query("SELECT * FROM receipt_items", conn)
conn.close()

if not df_summary.empty:
    most_common = df_summary['description'].value_counts().idxmax()
    highest_tax = df_summary['taxes'].max()
    most_expensive_item = df_summary.sort_values("unit_price", ascending=False).iloc[0]

    st.markdown(f"**Most Common Item:** {most_common}")
    st.markdown(f"**Highest Tax Paid:** ${highest_tax:.2f}")
    st.markdown(f"**Most Expensive Item:** {most_expensive_item['description']} at ${most_expensive_item['unit_price']:.2f}")

# Track Price History
st.markdown("---")
st.subheader("Track Price History of Item")
item_to_track = st.text_input("Enter item name to track (e.g. iPhone):", key="item_to_track")
if item_to_track:
    conn = sqlite3.connect(DB_PATH)
    df_history = pd.read_sql_query("""
        SELECT date, company_name, description, unit_price
        FROM receipt_items
        WHERE description LIKE ?
        ORDER BY date
    """, conn, params=(f"%{item_to_track}%",))
    conn.close()
    if not df_history.empty:
        available_companies = df_history['company_name'].unique().tolist()
        selected_companies = st.multiselect("Filter by company (optional):", available_companies, default=available_companies)

        filtered_df = df_history[df_history['company_name'].isin(selected_companies)]

        if not filtered_df.empty:
            st.markdown("#### Price Trend by Company")
            chart_data = filtered_df.copy()
            chart_data['date'] = pd.to_datetime(chart_data['date'])

            # Pivot for multi-line chart
            pivot_df = chart_data.pivot_table(index='date', columns='company_name', values='unit_price')
            st.line_chart(pivot_df)

            st.dataframe(filtered_df)
        else:
            st.write("No data found for selected company(ies).")
    else:
        st.write("No data found for this item.")

# Show cheapest price per unique item
if st.checkbox("Show cheapest price per unique item"):
    conn = sqlite3.connect(DB_PATH)
    cheapest = pd.read_sql_query("""
        SELECT company_name, description, MIN(unit_price) as cheapest_price
        FROM receipt_items
        GROUP BY description
        ORDER BY cheapest_price
    """, conn)
    conn.close()
    st.dataframe(cheapest)

# Export full database to Excel
if st.checkbox("Export full database to Excel"):
    conn = sqlite3.connect(DB_PATH)
    export_df = pd.read_sql_query("SELECT * FROM receipt_items", conn)
    conn.close()

    if not export_df.empty:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df.to_excel(writer, index=False, sheet_name='Receipts')
        output.seek(0)

        st.download_button(
            label="Download as Excel",
            data=output,
            file_name="receipts_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
