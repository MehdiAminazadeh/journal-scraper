import sys
import time
import signal
import pandas as pd
from tqdm import tqdm

from scrape_v2 import (
    INPUT_FILE,
    LOG_FILE,
    MANUAL_FILE,
    TARGET_YEARS,
    TARGET_JOURNALS,
    WP_DIR,
    vpn_connect,
    vpn_disconnect,
    close_driver,
    kill_leftover_chrome_processes,
    safe_str,
    parse_year,
    sanitize_filename,
    wp_available_flag,
    download_wp,
    li,
    lok,
    lwarn,
)


def run_wps_only():
    vpn_ok = vpn_connect()
    if not vpn_ok:
        print("WireGuard is required for this workflow. Stopping.")
        sys.exit(1)

    time.sleep(3)
    lok("VPN is up. Starting WORKING PAPERS ONLY workflow")

    def on_interrupt(sig, frame):
        lwarn("Interrupted. Closing browser and disconnecting VPN")
        close_driver()
        vpn_disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_interrupt)

    try:
        xl = pd.read_excel(INPUT_FILE, sheet_name=None)
        all_work_rows = []

        for sheet_name, df in xl.items():
            li("=" * 80)
            li(f"Sheet: {sheet_name} ({len(df)} rows)")
            li("=" * 80)

            for _, row in df.iterrows():
                journal = safe_str(row.get("journal", "") or sheet_name).upper().strip()
                year_pub = parse_year(row.get("year_pub", None))

                if TARGET_YEARS and year_pub not in TARGET_YEARS:
                    continue
                if TARGET_JOURNALS and journal not in TARGET_JOURNALS:
                    continue

                row_id = safe_str(row.get("id") or f"{sheet_name}_unknown")
                year_str = str(year_pub or "")
                last = safe_str(row.get("author1_last", ""))
                title = safe_str(row.get("paper_title", ""))

                base = sanitize_filename(f"{journal}_{year_str}_{last}")
                wp_dest = WP_DIR / f"{base}_WP.pdf"

                all_work_rows.append({
                    "sheet": sheet_name,
                    "row": row,
                    "id": row_id,
                    "title": title,
                    "journal": journal,
                    "year_pub": year_pub,
                    "wp_dest": wp_dest,
                })

        li(f"Total filtered rows to process for WPs: {len(all_work_rows)}\n")

        all_logs = {}

        for item in all_work_rows:
            row = item["row"]
            row_id = item["id"]
            title = item["title"]
            journal = item["journal"]
            year_pub = item["year_pub"]
            wp_dest = item["wp_dest"]
            sheet_name = item["sheet"]

            all_logs[row_id] = {
                "sheet": sheet_name,
                "id": row_id,
                "title": title[:150],
                "journal": journal,
                "year_pub": year_pub,
                "art_status": "SKIPPED_WP_ONLY_MODE",
                "art_doi": "",
                "art_hint": "",
                "art_tried": "",
                "art_file": "",
                "wp_status": "",
                "wp_series_used": "",
                "wp_hint": "",
                "wp_tried": "",
                "wp_file": str(wp_dest),
                "excel_wp_yes": safe_str(row.get("wp_yes", "")),
                "excel_wp_doi": safe_str(row.get("wp_doi", "")),
                "excel_wp_series": safe_str(row.get("wp_series", "")),
                "excel_wp_year": safe_str(row.get("wp_year", "")),
            }

        li("-" * 80)
        li("PHASE: DOWNLOADING WORKING PAPERS ONLY")
        li("-" * 80)

        for item in tqdm(all_work_rows, total=len(all_work_rows), desc="Working Papers"):
            row = item["row"]
            row_id = item["id"]
            title = item["title"]

            if not wp_available_flag(row):
                all_logs[row_id]["wp_status"] = "no_wp"
                continue

            li(f"\nWP {row_id} | {title[:90]}")
            wp = download_wp(row, item["wp_dest"])
            time.sleep(1.0)

            all_logs[row_id]["wp_status"] = wp.get("status", "")
            all_logs[row_id]["wp_series_used"] = wp.get("wp_series_used", "")
            all_logs[row_id]["wp_hint"] = wp.get("hint", "")
            all_logs[row_id]["wp_tried"] = wp.get("tried", "")

        log_df = pd.DataFrame(list(all_logs.values()))
        log_df.to_csv(LOG_FILE, index=False)

        wp_ok = log_df["wp_status"].fillna("").str.startswith("downloaded").sum()
        wp_ex = (log_df["wp_status"] == "already_exists").sum()
        wp_man = log_df["wp_status"].fillna("").str.startswith("MANUAL").sum()
        wp_none = (log_df["wp_status"] == "no_wp").sum()

        li("")
        li("=" * 80)
        li("WORKING PAPER DOWNLOAD SUMMARY")
        li("=" * 80)
        li(f"Processed rows: {len(log_df)}")
        li(f"Working papers downloaded: {wp_ok}")
        li(f"Working papers already existed: {wp_ex}")
        li(f"Working papers no WP available: {wp_none}")
        li(f"Working papers manual needed: {wp_man}")
        li(f"Log file: {LOG_FILE}")
        li("=" * 80)

        manual = log_df[
            log_df["wp_status"].fillna("").str.startswith("MANUAL")
        ].copy()

        if not manual.empty:
            manual["wp_url"] = manual["wp_hint"]
            manual[
                ["sheet", "id", "title", "journal", "year_pub",
                 "wp_status", "wp_series_used", "wp_url"]
            ].to_csv(MANUAL_FILE, index=False)

            li(f"Manual downloads list saved to {MANUAL_FILE} with {len(manual)} rows")

    finally:
        li("\n[FINAL CLEANUP] Closing all resources...")
        close_driver()
        kill_leftover_chrome_processes()
        vpn_disconnect()
        lok("Working-paper-only workflow complete")


if __name__ == "__main__":
    run_wps_only()