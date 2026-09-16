# IncuBrix: Growth Assessment Engine

 A high-throughput, quota-resilient lead generation engine engineered for zero-budget constraints. It bypasses strict API rate limits (RPM/RPD) using multi-key LLM rotation, zero-quota RSS web-scraping fallbacks, SQLite query deduplication, and automated content bottleneck analysis.

---

 ## 1\. Quick Start & Setup


```bash
# Clone the repository
git clone https://github.com/Sanjeevnathan-S/incubrix-growth-engine.git
cd incubrix-growth-engine

# Create and activate virtual environment
python -m venv venv

# Linux/macOS:
source venv/bin/activate

# Windows PowerShell:
# .\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```


---

 ## 2\. Project Architecture


```
incubrix-lead-pipeline/
├── config/
│   └── settings.py          # Global settings, 7 target GEOs, API key rotation configs
├── data/
│   ├── cache.db             # SQLite DB for lead storage & search history deduplication
│   └── processed/           # Export directory
│       ├── leads.csv        # Formatted CSV lead exports
│       └── leads.xlsx       # Excel workbook exports
├── src/
│   ├── discovery/
│   │   ├── podcast_client.py    # Apple Podcasts API client across 7 country endpoints
│   │   ├── scrapetube_client.py # Zero-quota YouTube scraper + parallel RSS enrichment
│   │   └── youtube_client.py    # Official YouTube Data API v3 fallback discovery
│   ├── enrichment/
│   │   ├── bottleneck_check.py  # Long-form vs. short-form content gap & hook analyzer
│   │   ├── link_scrapper.py     # Commercial bio link & direct contact email extractor
│   │   └── rss_parser.py        # RSS XML parser for itunes:owner & show-note contacts
│   ├── export/
│   │   └── exporter.py          # Safe exporter triggered on completion or Ctrl+C
│   ├── filtering/
│   │   └── llm_classifier.py    # Multi-key Gemini model evaluator with 429 fallback
│   └── storage/
│       └── db.py                # Main lead database & country ratio window filters
├── main.py                      # Master pipeline orchestration loop & interrupt handler
└── README.md                    # System documentation

```


---

 ## 3\. System Architecture & Workflow

```
                           +------------------------+
                           | Target Search Query    |
                           +------------------------+
                                       |
                                       v
                       +--------------------------------+
                       | 30-Day Query TTL Check         |
                       | (data/cache.db)                |
                       +--------------------------------+
                          /                          \
                 [Hit]   /                            \  [Miss]
                        v                              v
         +----------------------------+   +------------------------------------+
         | Skip Query Execution       |   | Discovery Layer (7 Target GEOs)    |
         +----------------------------+   |  1. Apple Podcasts API             |
                                          |  2. YouTube Data API (If quota OK) |
                                          |  3. Scrapetube + Parallel RSS      |
                                          +------------------------------------+
                                                           |
                                                           v
                                          +------------------------------------+
                                          | Multi-Source Enrichment Engine     |
                                          |  - LinkScraper (Linktree, Emails)  |
                                          |  - RSSParser (itunes:owner tags)   |
                                          |  - BottleneckAnalyzer (Shorts gap) |
                                          +------------------------------------+
                                                           |
                                                           v
                                          +------------------------------------+
                                          | Multi-Key LLM Qualification        |
                                          | (Rotates 3x Free Gemini Keys)      |
                                          +------------------------------------+
                                                           |
                                                           v
                                          +------------------------------------+
                                          | SQLite Persistence & Tier-1 Filter |
                                          | Exports to CSV & XLSX on SIGINT    |
                                          +------------------------------------+

```


---

 ## 4\. Quota Optimization & Resiliency Strategy

 ### 1\. Multi-Key Gemini Rotation (`llm_classifier.py`)

 To maximize processing throughput under Free-Tier Resource Per Day (RPD) and Requests Per Minute (RPM) constraints, the pipeline cycles across 3 separate Gemini API keys. If Key 1 triggers a `429 Rate Limit Exceeded` or `404 Service Unavailable` response, the classifier dynamically shifts active execution to Key 2 or Key 3 without dropping pipeline state.

 ### 2\. Zero-Quota Scrapetube & RSS Fallback (`scrapetube_client.py`)

 When official YouTube Data API quotas deplete to 0, discovery automatically falls back to `scrapetube` combined with multithreaded RSS parsing using `ThreadPoolExecutor`. This retrieves channel metadata and recent uploads without consuming official YouTube Data API credits.

 ### 3\. SQLite Query Deduplication & Retention (`db.py`)

 - **30-Day Query TTL:** Caches executed search terms in `search_history` with a 30-day TTL window to avoid redundant API queries across repeated discovery cycles.
- **90-Day Stale Purging:** Automatically purges non-qualified candidates older than 90 days (`clear_stale_disqualifications`) while permanently retaining qualified lead profiles.
- **Geographic & Ratio Filters:** Enforces export balance rules during candidate retrieval (`export_all_qualified`), capping single-country dominance at $\\le 60%$ and guaranteeing $\\ge 80%$ aggregate Tier-1 English market distribution.

---

 ## 5\. Performance Benchmarks

 Metrics calculated across execution runs targeting 7 country regions (`US`, `CA`, `GB`, `IE`, `AU`, `NZ`, `SG`):

 | Discovery Engine | Quota Cost | Avg Latency / Geo | Lead Yield / Query | Memory Footprint |
| --- | --- | --- | --- | --- |
| **Apple Podcasts API** | **0 Units (Free)** | \~1.8 seconds | 20–25 Qualified Leads | \~45 MB RSS |
| **YouTube Data API v3** | **100 Units / Search** | \~0.9 seconds | 15–20 Qualified Leads | \~50 MB RSS |
| **Scrapetube + RSS Fallback** | **0 Units (Free)** | \~4.5 seconds (10 threads) | 15–20 Qualified Leads | \~85 MB RSS |

> **Note:** Benchmark figures are environment-dependent and should be treated as indicative rather than guaranteed.

---

 ## 6\. Execution Guide

 ### Run Standard Discovery Loop

````
```bash
python main.py

```
````

 ### Safe Interrupt & Export (`Ctrl+C`)

 The main loop registers standard system signals (`SIGINT`). Pressing `Ctrl+C` halts active processing safely and immediately executes `src/export/exporter.py`. All qualified leads gathered up to that point are preserved and exported to:

 - `data/processed/leads.csv`
- `data/processed/leads.xlsx`

---

 ## 7\. Failure Analysis & Risk Mitigations


```
                        Failure Point & Engineering Solution

    Detected Issue                Root Cause                 Pipeline Mitigation
┌──────────────────────┐    ┌───────────────────────────┐    ┌────────────────────────────┐
│ API Quota Exhaustion │ ──►│ Single API Key Exceeding  │ ──►│ Automatic key-rotation     │
│ (429 Rate Limit)     │    │ Free-Tier Daily Quotas    │    │ (3x Gemini Keys)           │
└──────────────────────┘    └───────────────────────────┘    └────────────────────────────┘

┌──────────────────────┐    ┌───────────────────────────┐    ┌────────────────────────────┐
│ Missing Contact Email│ ──►│ Hidden or unlisted creator│ ──►│ Bio regex + RSS XML        │
│ in API Metadata      │    │ business emails           │    │ landing page scraping      │
└──────────────────────┘    └───────────────────────────┘    └────────────────────────────┘

┌──────────────────────┐    ┌───────────────────────────┐    ┌────────────────────────────┐
│ Redundant Discovery  │ ──►│ Repeated execution of     │ ──►│ 30-day query TTL check     │
│ Calls Across Runs    │    │ identical search queries  │    │ via SQLite search_history   │
└──────────────────────┘    └───────────────────────────┘    └────────────────────────────┘

```


---

 ## 8\. Development Roadmap


```
                                Product Roadmap

    Phase 1 (Current)                Phase 2 (Near-Term)            Phase 3 (Scale)
┌─────────────────────────┐      ┌─────────────────────────┐    ┌─────────────────────────┐
│ • Apple + YouTube API   │ ───► │ • Async HTTP Engine     │ ──►│ • Multi-LLM Routing     │
│ • Scrapetube RSS        │      │ • Headless Bio Scraper  │    │   (Ollama / DeepSeek)   │
│ • 3x Gemini Key Rotation│      │ • SQLite WAL Concurrency│    │ • Automated Outreach    │
└─────────────────────────┘      └─────────────────────────┘    └─────────────────────────┘

```


---

 ## License

 MIT License. See project repository for details.

 ## Disclaimer

 API quotas, service availability, scraping behavior, and third-party platform policies can change. Ensure your implementation complies with the applicable terms of service, robots directives, privacy requirements, and API policies of each platform.