# Husk & Fibre — Agro-Material Business Intelligence

A dashboard + newsletter feed of agro-waste materials (coconut, banana, bamboo,
palm, mango...) turning into real, sellable products — with a headline, a
business-potential rating, a detailed brief, and a video for every story.

## What's in this folder

```
index.html              the website (dashboard + newsletter views)
data.json                the content — 10 real, sourced seed stories
videos/                  8 short video clips (yours, from Instagram) used as the story videos
pipeline/scrape_and_score.py    the automated ingestion script — no human review step
.github/workflows/refresh.yml   schedules that script to run every 6 hours, free, on GitHub
```

## Try it right now

Open `index.html` in a browser (double-click it, or run `python3 -m http.server`
in this folder and visit `http://localhost:8000`). Toggle between **Dashboard**
and **Newsletter**, filter by material, click any story for the full brief and
sources.

## Honest note on "fully automated, no human step"

You asked for this to run without you approving each item, so here's exactly
what that means and where the real limits are:

- **What the pipeline (`pipeline/scrape_and_score.py`) does automatically:**
  pulls fresh items from RSS feeds (Down To Earth, The Better India,
  Mongabay-India) and, if you add a free NewsAPI key, from a broader news
  search; tags each item by material (coconut/banana/bamboo/palm/mango/straw)
  using keyword matching; scores "business potential" with a simple heuristic
  (counts business-signal words like *startup*, *export*, *revenue*); searches
  YouTube's official API for a matching video; and writes everything straight
  into `data.json` — no person reads or approves any of this before it goes
  live.

- **What it deliberately does *not* do, and why:** it does not download video
  files from Instagram or YouTube. Scraping video off those platforms breaks
  their Terms of Service and the original creator's copyright, regardless of
  the purpose — so I didn't build that part, even though you asked for full
  automation. Instead, new stories get an *embedded* official YouTube player
  (an iframe pointing at the real video ID), which is fully legal, keeps the
  creator's view count intact, and won't silently go stale like a downloaded
  copy would. The 8 videos already in `videos/` are ones you had already saved
  — I used those as real seed content, but the automated pipeline going forward
  embeds rather than downloads.

- **The keyword/scoring filter is code, not a person** — so it satisfies "no
  human step" — but it is a first pass, not a finished relevance model. Expect
  some noise until you tune the keyword lists in `MATERIAL_KEYWORDS` and
  `BUSINESS_SIGNAL_WORDS` at the top of the script against a few weeks of
  real output.

## Making it live and public

This is a static site (no server code needed to *display* it), so the
cheapest public-hosting path is:

1. Push this folder to a GitHub repository.
2. Turn on **GitHub Pages** for that repo (Settings → Pages → deploy from
   `main` branch) — you'll get a free `https://yourname.github.io/reponame/`
   URL in a couple of minutes.
3. Add two repo secrets so the automated refresh can search a wider net:
   `NEWSAPI_KEY` (free tier at newsapi.org) and `YOUTUBE_API_KEY` (free at
   console.cloud.google.com, enable "YouTube Data API v3").
4. The included `.github/workflows/refresh.yml` will then run every 6 hours,
   run the pipeline, and commit the updated `data.json` automatically —
   GitHub Pages picks up the change on the next visit, with zero manual steps.

If you'd rather have a real domain and a bit more control, the same three
files (`index.html`, `data.json`, `videos/`) deploy as-is to Netlify or
Vercel's free static hosting — drag-and-drop the folder in either dashboard.

## Extending it

- **More materials:** add a row to `MATERIAL_KEYWORDS` in the pipeline script
  and a matching entry will start getting tagged automatically.
- **Better scoring:** the current "business potential" score is a rough
  keyword heuristic. A natural next step is swapping it for a small call to
  an LLM (e.g. the Claude API) that reads each article and returns a score
  and one-paragraph explanation — happy to wire that in if useful.
- **Instagram:** Instagram's official API doesn't support searching public
  reels by keyword the way YouTube's does, so there's no equivalent
  legal auto-discovery path there today. The practical option is to keep
  manually saving reels you find (the way this conversation started) and
  dropping them in `videos/` with an entry in `data.json` — everything else
  in the dashboard already supports that.
