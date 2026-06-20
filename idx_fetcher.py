import os
from datetime import datetime, timedelta
import cloudscraper

BASE_URL = "https://www.idx.co.id/primary/list/id/perusahaan-tercatat/data-kepemilikan-saham/"
DOWNLOAD_DIR = "downloads"


def fetch_idx_pdf(exact_date=None):
    """
    Fetch IDX 5% shareholder data from the new endpoint.
    Automatically skips download if file already exists based on date in filename.

    Parameters
    ----------
    exact_date : str | None
        If None -> fetch latest.
        If given -> fetch only file that matches the exact date (YYYYMMDD).

    Returns
    -------
    dict
        {
            'title', 'announcementDate', 'attachmentUrl',
            'fileName', 'savedPath'
        }

    Raises
    ------
    ValueError
        If no data found.
    """
    scraper = cloudscraper.create_scraper()
    
    # We will search the current year and the previous year if we are looking for the latest file.
    current_year = datetime.today().year
    years_to_check = [current_year, current_year - 1]
    
    items = []
    if exact_date:
        year = exact_date[:4]
        url = f"{BASE_URL}?start=0&length=9999&year={year}"
        response = scraper.get(url)
        response.raise_for_status()
        items = response.json().get("items", [])
    else:
        for yr in years_to_check:
            url = f"{BASE_URL}?start=0&length=9999&year={yr}"
            try:
                response = scraper.get(url)
                if response.status_code == 200:
                    yr_items = response.json().get("items", [])
                    items.extend(yr_items)
            except Exception:
                pass

    # Filter items to only include those relevant to 5% shareholders
    filtered_items = []
    for item in items:
        desc = item.get("Description", "")
        url = item.get("Prospectus", "")
        if not url:
            continue
        # Check for 5% shareholder keywords in URL or description
        is_five_percent = (
            "lima-persen" in url.lower() or 
            "di atas 5%" in desc.lower() or 
            "diatas 5%" in desc.lower() or 
            "5%" in desc.lower()
        )
        if is_five_percent:
            filtered_items.append(item)

    # Sort descending by ListingDate to ensure latest is first
    filtered_items.sort(key=lambda x: x.get("ListingDate", ""), reverse=True)

    target_item = None
    if exact_date:
        for item in filtered_items:
            listing_date = item.get("ListingDate", "")
            if len(listing_date) >= 10:
                date_str = datetime.strptime(listing_date[:10], "%Y-%m-%d").strftime("%Y%m%d")
                if date_str == exact_date:
                    target_item = item
                    break
    else:
        if filtered_items:
            target_item = filtered_items[0]

    if not target_item:
        raise ValueError(f"No 5% shareholder data found for the given parameters (exact_date: {exact_date})")

    description = target_item.get("Description", "")
    pdf_url = target_item.get("Prospectus", "")
    listing_date = target_item.get("ListingDate", "")
    
    # Extract date_str from listing_date
    if len(listing_date) >= 10:
        date_str = datetime.strptime(listing_date[:10], "%Y-%m-%d").strftime("%Y%m%d")
    else:
        date_str = datetime.today().strftime("%Y%m%d")

    # Get original filename from URL
    original_filename = pdf_url.split("/")[-1] if "/" in pdf_url else "data.xlsx"
    file_name = f"{date_str}_{original_filename}"
    
    # Check if download directory exists
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # Check if file already exists in downloads (by prefix date_str)
    existing_files = os.listdir(DOWNLOAD_DIR)
    matching_files = [f for f in existing_files if f.startswith(date_str)]
    
    if matching_files:
        saved_filename = matching_files[0]
        save_path = os.path.join(DOWNLOAD_DIR, saved_filename)
        print(f"File already exists for date {date_str}, skipping download.")
        return {
            "title": description,
            "announcementDate": listing_date,
            "attachmentUrl": pdf_url,
            "fileName": saved_filename,
            "savedPath": save_path
        }

    save_path = os.path.join(DOWNLOAD_DIR, file_name)
    print(f"Downloading {file_name} from {pdf_url} ...")
    
    pdf_data = scraper.get(pdf_url)
    pdf_data.raise_for_status()
    with open(save_path, "wb") as f:
        f.write(pdf_data.content)
    print(f"Saved to {save_path}")

    return {
        "title": description,
        "announcementDate": listing_date,
        "attachmentUrl": pdf_url,
        "fileName": file_name,
        "savedPath": save_path
    }
