from datetime import datetime
import threading
from tkinter import ttk
import pandas as pd
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.tooltip import ToolTip
from pdf_parser import parse_shareholder_pdf
from idx_fetcher import fetch_idx_pdf
from helper import resource_path

# ---------- Window & state ----------
root = tb.Window(themename="litera")
root.iconbitmap(resource_path("assets/app.ico"))
root.title("IDX Shareholder Parser")
root.geometry("1000x650")

mode_var = tb.StringVar(value="latest")  # 'latest' or 'exact'
simple_view_var = tb.BooleanVar(value=True)
table_df = pd.DataFrame()

# ---------- Helper UI state ----------


def set_ui_state(state):
    fetch_button.config(state=state)
    radio_latest.config(state=state)
    radio_exact.config(state=state)
    date_entry.config(state=(state if mode_var.get() == "exact" else DISABLED))
    simple_view_check.config(state=state)


def log_to_label(text):
    root.after(0, lambda: fetch_status_label.config(text=text))

# ---------- Fetch / parse ----------


def fetch_parse_thread():
    current_mode = mode_var.get()
    set_ui_state(DISABLED)
    fetch_status_label.config(text="Fetching...")

    exact_date = None
    if current_mode == "exact":
        text = date_entry.get().strip()
        if not text:
            root.after(0, lambda: Messagebox.show_error(
                "Please enter a date (YYYY-MM-DD)", "Invalid Date"))
            set_ui_state(NORMAL)
            fetch_status_label.config(text="")
            return
        try:
            exact_date = datetime.strptime(text, "%Y-%m-%d").strftime("%Y%m%d")
        except ValueError:
            root.after(0, lambda: Messagebox.show_error(
                "Date format must be YYYY-MM-DD", "Invalid Date"))
            set_ui_state(NORMAL)
            fetch_status_label.config(text="")
            return

    try:
        result = fetch_idx_pdf(exact_date=exact_date)
        df = parse_shareholder_pdf(result["savedPath"], log_to_label)
        global table_df
        table_df = df
        root.after(0, lambda: display_table(df))
    except Exception as e:
        error_msg = str(e)
        root.after(0, lambda: Messagebox.show_error(error_msg, "Error"))
        root.after(0, lambda: fetch_status_label.config(text="Error occurred.", bootstyle="danger"))
    finally:
        root.after(0, lambda: set_ui_state(NORMAL))
        # Clear status after 5 seconds
        root.after(5000, lambda: fetch_status_label.config(text=""))


def fetch_and_parse():
    threading.Thread(target=fetch_parse_thread, daemon=True).start()

# ---------- Display table ----------


def display_table(df: pd.DataFrame):
    for w in table_frame.winfo_children():
        w.destroy()

    if df.empty:
        tb.Label(table_frame, text="No data to display",
                 anchor="w").pack(fill="x", padx=10, pady=10)
        return

    if simple_view_var.get():
        simple_cols = ["No", "Kode Efek",
                       "Nama Pemegang Rekening Efek", "Perubahan"]
        visible_cols = [c for c in simple_cols if c in df.columns]
    else:
        visible_cols = list(df.columns)

    if "No" not in df.columns:
        df = df.copy()
        df.insert(0, "No", range(1, len(df) + 1))

    container = tb.Frame(table_frame)
    container.pack(fill="both", expand=True, padx=8, pady=6)

    vscroll = tb.Scrollbar(container, orient="vertical")
    vscroll.pack(side="right", fill="y")
    hscroll = tb.Scrollbar(container, orient="horizontal")
    hscroll.pack(side="bottom", fill="x")

    tree = tb.Treeview(
        container,
        columns=visible_cols,
        show="headings",
        yscrollcommand=vscroll.set,
        xscrollcommand=hscroll.set,
        bootstyle="info"
    )
    tree.pack(fill="both", expand=True)

    vscroll.config(command=tree.yview)
    hscroll.config(command=tree.xview)

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

    for col in visible_cols:
        if col == "No":
            tree.column(col, width=70, anchor="center", stretch=False)
        elif col in numeric_cols:
            tree.column(col, width=140, anchor="e", stretch=True)
        else:
            tree.column(col, width=220, anchor="w", stretch=True)
        tree.heading(col, text=col)

    tree.tag_configure("pos", foreground="green")
    tree.tag_configure("neg", foreground="red")
    tree.tag_configure("zero", foreground="black")

    prev_emiten = None
    rows = []
    for _, row in df.iterrows():
        current_emiten = row.get("Kode Efek", "")
        if prev_emiten is not None and current_emiten != prev_emiten:
            sep = ["-"*10] * len(visible_cols)
            rows.append((sep, "sep"))

        vals = []
        for col in visible_cols:
            val = row.get(col, "")
            if pd.isna(val):
                val = ""
            elif col == "No":
                try:
                    val = str(int(val))
                except:
                    val = str(val)
            elif col in numeric_cols:
                try:
                    if isinstance(val, float) and not val.is_integer():
                        val = f"{val:,.2f}".replace(",", ".")
                    else:
                        val = f"{int(val):,}".replace(",", ".")
                except:
                    val = str(val)
            else:
                val = str(val)
            vals.append(val)

        tag = "zero"
        if "Perubahan" in df.columns:
            try:
                raw = row.get("Perubahan", 0)
                if pd.isna(raw) or raw == 0:
                    tag = "zero"
                elif raw > 0:
                    tag = "pos"
                else:
                    tag = "neg"
            except:
                tag = "zero"

        rows.append((vals, tag))
        prev_emiten = current_emiten

    for i, (vals, tag) in enumerate(rows):
        if tag == "sep":
            tree.insert("", "end", values=vals)
        else:
            tree.insert("", "end", values=vals, tags=(tag,))
        if i % 200 == 0:
            tree.update_idletasks()

# ---------- Toggle handlers ----------


def toggle_date_picker():
    if mode_var.get() == "exact":
        date_entry.config(state=NORMAL)
    else:
        date_entry.config(state=DISABLED)


def toggle_view():
    if not table_df.empty:
        display_table(table_df)

# ---------- Layout ----------


top_frame = tb.Frame(root)
top_frame.pack(fill="x", padx=10, pady=8)

# Row 1: Fetch mode + optional date
mode_row = tb.Frame(top_frame)
mode_row.pack(fill="x", pady=(0, 6))

tb.Label(mode_row, text="Select Fetch Mode:",
         style=HEADINGS).pack(side="left", padx=(0, 6))

radio_latest = tb.Radiobutton(mode_row, text="Latest", variable=mode_var, value="latest",
                              command=toggle_date_picker, bootstyle="info-toolbutton")
radio_latest.pack(side="left", padx=4)

# Add separator for clarity
tb.Separator(mode_row, orient="vertical").pack(
    side="left", fill="y", padx=8, pady=2)

radio_exact = tb.Radiobutton(mode_row, text="Pick Exact Date", variable=mode_var, value="exact",
                             command=toggle_date_picker, bootstyle="info-toolbutton")
radio_exact.pack(side="left", padx=4)

date_frame = tb.Frame(mode_row)
date_frame.pack(side="left", padx=8)

date_entry = tb.Entry(date_frame, width=12)
date_entry.pack(side="left")
date_entry.insert(0, datetime.today().strftime("%Y-%m-%d"))
date_entry.config(state=DISABLED)

# Tooltip for date format
ToolTip(date_entry, text="Enter date in YYYY-MM-DD format",
        bootstyle=(INFO, INVERSE))

# Row 2: Fetch button + simple view + status
action_row = tb.Frame(top_frame)
action_row.pack(fill="x")

fetch_button = tb.Button(action_row, text="Fetch",
                         command=fetch_and_parse, bootstyle="primary")
fetch_button.pack(side="left")

simple_view_check = tb.Checkbutton(action_row, text="Simple View", variable=simple_view_var,
                                   command=toggle_view, bootstyle="success-roundtoggle")
simple_view_check.pack(side="left", padx=12)

fetch_status_label = tb.Label(action_row, text="", bootstyle="info")
fetch_status_label.pack(side="left", padx=10)
ttk.Separator(root, orient='horizontal').pack(fill='x', padx=10, pady=(5, 5))

# Table frame
table_frame = tb.Frame(root)
table_frame.pack(fill="both", expand=True, padx=10, pady=8)

root.mainloop()
