import os
import numpy as np
import pdfplumber
import pandas as pd
import re

RESULT_DIR = "results"
os.makedirs(RESULT_DIR, exist_ok=True)


def parse_shareholder_pdf(pdf_path: str, log_callback=None) -> pd.DataFrame:
    """
    Parse a shareholder ownership PDF from IDX (Pemegang Saham di atas 5%) and
    return a cleaned DataFrame containing relevant information.
    Skips parsing if CSV already exists in the results folder.

    Args:
        pdf_path (str): Path to the PDF file

    Returns:
        pd.DataFrame: Filtered DataFrame of affected emitens
    """

    # Determine corresponding CSV path
    pdf_filename = os.path.basename(pdf_path)
    csv_filename = os.path.splitext(pdf_filename)[0] + ".csv"
    csv_path = os.path.join(RESULT_DIR, csv_filename)

    if os.path.exists(csv_path):
        if log_callback:
            log_callback(f"CSV already exists, loading from {csv_path}")
        print(f"CSV already exists, loading from {csv_path}")

        return pd.read_csv(csv_path)

    # --- Parse PDF ---
    all_rows = []
    final_header = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        
        for idx, page in enumerate(pdf.pages, start=1):
            if log_callback:
                log_callback(f"Scanning page {idx} of {total_pages}...")
            
            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Check if this table contains our data by looking for keywords in the first few rows
                is_data_table = False
                header_row_idx = -1
                
                for r_idx, row in enumerate(table[:5]): # check first 5 rows of the table
                    row_str = " ".join([str(cell) for cell in row if cell]).lower()
                    if "kode efek" in row_str or "nama emiten" in row_str or ("efek" in row_str and len(row) >= 10):
                        is_data_table = True
                        header_row_idx = r_idx
                        break
                
                if not is_data_table and not final_header:
                    continue # Skip intro tables

                if not final_header:
                    raw_header = table[header_row_idx]
                    # Get sub-header row (the row below the main header, for multi-level headers)
                    sub_header = table[header_row_idx + 1] if header_row_idx + 1 < len(table) else []

                    # Clean header
                    i = 0
                    while i < len(raw_header):
                        h = (raw_header[i] or "").strip().replace("\n", " ")
                        if "kepemilikan per" in h.lower():
                            m = re.search(r"(\d{1,2}-[A-Z]{3}-\d{4})", h)
                            date_str = m.group(1) if m else "Date"

                            # Find where this Kepemilikan group ends in the main header
                            group_end = i + 1
                            while group_end < len(raw_header) and (not raw_header[group_end] or not raw_header[group_end].strip()):
                                group_end += 1

                            # Count sub-columns from the sub-header row, bounded by the next main header column
                            sub_cols = []
                            j = i
                            while j < group_end and j < len(sub_header) and sub_header[j] and sub_header[j].strip():
                                sub_cols.append(sub_header[j].strip().replace("\n", " "))
                                j += 1

                            if sub_cols:
                                for sc in sub_cols:
                                    final_header.append(f"{sc} ({date_str})")
                                i += len(sub_cols)
                            else:
                                # Fallback: assume 3 sub-columns (old format without extra columns)
                                final_header.extend([
                                    f"Jumlah Saham ({date_str})",
                                    f"Saham Gabungan ({date_str})",
                                    f"Persentase ({date_str})"
                                ])
                                i += 3
                        else:
                            if h:
                                final_header.append(h)
                            else:
                                final_header.append(f"Col_{i}")
                            i += 1

                    # Fix common garbled header names from PDF text extraction
                    header_fixes = {
                        "keofedke": "Kode Efek",
                        "(loksatal/taussi ng)": "Status (Lokal/Asing)",
                    }
                    final_header = [header_fixes.get(h.strip().lower(), h) for h in final_header]

                    data = table[header_row_idx + 1:]
                else:
                    # On subsequent pages/tables, skip rows that look like headers
                    first_row_str = " ".join([str(x) for x in table[0] if x]).lower()
                    if "kode efek" in first_row_str or "nama emiten" in first_row_str or ("efek" in first_row_str and len(table[0]) >= 10):
                        data = table[1:]
                    else:
                        data = table
                
                # Only add rows that have content and roughly match header length
                for row in data:
                    if any(row) and len([c for c in row if c]) > 2:
                        all_rows.append(row)

    if not all_rows:
        if log_callback:
            log_callback("No valid data table found in PDF.")
        return pd.DataFrame()

    # Ensure all rows have the same length as final_header
    cleaned_rows = []
    for r in all_rows:
        if len(r) == len(final_header):
            cleaned_rows.append(r)
        elif len(r) > len(final_header):
            cleaned_rows.append(r[:len(final_header)])
        else:
            cleaned_rows.append(r + [None] * (len(final_header) - len(r)))

    df = pd.DataFrame(cleaned_rows, columns=final_header)
    
    # Filter out rows where 'Kode Efek' is not a valid code (usually 4 uppercase letters)
    if "Kode Efek" in df.columns:
        df = df[df["Kode Efek"].astype(str).str.match(r"^[A-Z0-9]{4}$", na=False)]


    # Drop unnecessary columns
    for col in ["Alamat", "Alamat (Lanjutan)", "Domisili"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Clean string data
    for col in df.columns:
        df[col] = (
            df[col]
            .astype(str)
            .str.strip()
            .replace(["None", "none", "", "nan"], np.nan)
        )

    # Convert numeric columns (use startswith to avoid matching "Nama Pemegang Saham" etc.)
    for col in df.columns:
        if col.startswith("Jumlah") or col.startswith("Saham") or "Persentase" in col or col == "Perubahan":
            df[col] = df[col].str.replace(",", "", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Identify the change column
    # If the PDF already has a 'Perubahan' column, use it.
    if "Perubahan" in df.columns:
        # Some rows might have Perubahan as a string '0' or a number 0
        filtered_df = df[df["Perubahan"] != 0].copy()
    else:
        # Fallback to calculating from percentage columns if Perubahan doesn't exist
        perc_cols = [c for c in df.columns if "Persentase" in c]
        if len(perc_cols) >= 2:
            prev_col, curr_col = perc_cols[-2], perc_cols[-1]
            df["Perubahan"] = df[curr_col] - df[prev_col]
            filtered_df = df[df["Perubahan"] != 0].copy()
        else:
            filtered_df = df.copy()

    # Save CSV for next time
    if not filtered_df.empty:
        filtered_df.to_csv(csv_path, index=False)
        if log_callback:
            log_callback(f"Done. Found {len(filtered_df)} affected rows.")
    else:
        if log_callback:
            log_callback("Done. No changes found in this PDF.")
    
    print(f"Parsed and saved CSV to {csv_path}")
    return filtered_df
