"""
Stage 1-2: filter the raw Amazon Electronics reviews down to the ones that
carry at least one reviewer photo, and write them out in the flat shape
Stage 3 (prepare_app_data.py) expects.

Source: McAuley-Lab/Amazon-Reviews-2023, config "raw_review_Electronics"
(the review-level sibling of the "raw_meta_Electronics" config that
prepare_app_data.py already streams for product metadata).

Run this once, before prepare_app_data.py.
"""

import json
import gzip
from pathlib import Path

# ----------------------------- config -----------------------------
OUT_FILE = Path(r"E:\work_dsi\Nagbhushan_Data_Creation_Amazon\datasets\amazon2023\out\electronics_image_reviews.jsonl")

REVIEW_MODE = "stream"               # "stream" or "local"
LOCAL_REVIEW_FILE = Path(r"E:\work_dsi\Nagbhushan_Data_Creation_Amazon\datasets\amazon2023\raw_review_Electronics.jsonl")

PROGRESS_EVERY = 200_000
# ------------------------------------------------------------------


def iter_reviews():
    if REVIEW_MODE == "stream":
        from datasets import load_dataset
        ds = load_dataset(
            "McAuley-Lab/Amazon-Reviews-2023",
            "raw_review_Electronics",
            split="full",
            streaming=True,
            trust_remote_code=True,
        )
        for rec in ds:
            yield rec
    else:
        opener = gzip.open if LOCAL_REVIEW_FILE.suffix == ".gz" else open
        with opener(LOCAL_REVIEW_FILE, "rt", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if line:
                    yield json.loads(line)


def image_urls(images):
    """Pull the best available URL out of each attached-image struct."""
    urls = []
    for img in images or []:
        if not isinstance(img, dict):
            continue
        url = img.get("large_image_url") or img.get("medium_image_url") or img.get("small_image_url")
        if url:
            urls.append(url)
    return urls


def main():
    print("Scanning raw Electronics reviews for ones with photos...")
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    seen = 0
    kept = 0
    with OUT_FILE.open("w", encoding="utf-8") as out:
        for rec in iter_reviews():
            seen += 1
            if seen % PROGRESS_EVERY == 0:
                print(f"  scanned {seen:,} reviews, kept {kept:,}", flush=True)

            urls = image_urls(rec.get("images"))
            if not urls:
                continue
            if not rec.get("parent_asin"):
                continue

            row = {
                "parent_asin": rec.get("parent_asin"),
                "asin": rec.get("asin"),
                "user_id": rec.get("user_id"),
                "timestamp": rec.get("timestamp"),
                "rating": rec.get("rating"),
                "title": rec.get("title"),
                "text": rec.get("text"),
                "verified_purchase": rec.get("verified_purchase"),
                "helpful_vote": rec.get("helpful_vote"),
                "image_urls": urls,
                "n_images": len(urls),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            kept += 1

    print(f"\nScanned {seen:,} reviews, wrote {kept:,} with photos to {OUT_FILE}")


if __name__ == "__main__":
    main()
