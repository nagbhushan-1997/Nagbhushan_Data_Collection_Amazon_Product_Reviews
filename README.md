# Cross-modal review checker

A Streamlit app for annotating whether a reviewer's photo agrees with what
they wrote. Search a product, see its catalog photos next to each reviewer's
photo and text, and record a verdict per review.

## Project layout

- `app.py` — the annotation app (`streamlit run app.py`)
- `prepare_image_reviews.py` / `prepare_app_data.py` — one-time scripts that
  build `products.jsonl` from the raw McAuley-Lab/Amazon-Reviews-2023 dataset
- `products.jsonl` — the data the app reads (not committed, see below)
- `annotations.db` — SQLite file the app writes judgements to (not committed;
  created automatically on first run)

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

`products.jsonl` (~290MB) is too large for git, so it's not in this repo.
Either:
- copy your own `products.jsonl` next to `app.py`, or
- set `HF_DATASET_REPO` (and `HF_TOKEN` if the dataset is private) as
  environment variables — the app will download it automatically from a
  Hugging Face dataset repo on first run and cache it locally.

## Deploying so others can annotate

1. **Host `products.jsonl`** on a Hugging Face dataset repo (free, handles
   large files):
   ```bash
   huggingface-cli login   # paste a token with write access
   huggingface-cli upload <your-username>/<dataset-name> products.jsonl products.jsonl --repo-type dataset
   ```
   Make the dataset private if the underlying review data shouldn't be public.

2. **Push this repo to GitHub** (see below).

3. **Deploy on [Streamlit Community Cloud](https://streamlit.io/cloud)**:
   - Sign in with GitHub, click "New app", pick this repo and `app.py`.
   - Under "Advanced settings" → Secrets, add:
     ```toml
     HF_DATASET_REPO = "<your-username>/<dataset-name>"
     HF_TOKEN = "<a read-only HF token, only needed if the dataset is private>"
     ```
   - Deploy. Streamlit gives you a public URL — share that with your friends.

Everyone who opens the link annotates against the same shared
`annotations.db` on that running instance (it resets if the app redeploys or
sleeps from inactivity long enough to be recycled — export judgements via the
"Download all judgements (CSV)" button in the sidebar periodically if you
want to keep them).
