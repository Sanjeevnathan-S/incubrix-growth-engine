# AI Assistance Disclosure

 This document discloses the use of AI assistance in the design, implementation, and optimization of the **Incrubrix: Growth Assessment** pipeline.

---

 ## 1\. Scope of AI Assistance

 AI tools (specifically Large Language Models) were utilized as a collaborative partner throughout the software development lifecycle across the following areas:

 - **System Architecture & Pipeline Engineering:** Designing the execution flow, defining error-handling mechanisms for rate limits (`429`), and establishing a fallback hierarchy (Apple Podcasts API → YouTube API → Scrapetube + Parallel RSS).
- **Code Implementation & Refactoring:**
  - Generation and optimization of Python scripts across discovery, enrichment, filtering, and export modules.
  - Thread-safe SQLite caching implementation (`data/cache.db`) utilizing Write-Ahead Logging (`PRAGMA journal_mode=WAL`).
  - Concurrency patterns using Python's `concurrent.futures.ThreadPoolExecutor` for RSS parsing.
- **Resiliency & Quota Management Strategies:** Structuring multi-key API key rotation algorithms (handling 3x Gemini API keys) and gracefully handling process interruption via system signal handlers (`SIGINT` / `Ctrl+C`).
- **Regex & Scraper Optimization:** Crafting regular expressions for link extraction, email detection, subword tokenization fixes, and commercial platform classification (`linktr.ee`, `beacons.ai`, `patreon.com`).
- **Documentation & Technical Writing:** Generating technical architectural diagrams, project benchmarks, setup guides, and structural Markdown documentation (`README.md`, `TECHNICAL_REPORT.md`).

---

 ## 2\. Human Verification & Oversight

 All AI-generated code and architectural recommendations underwent human review and testing:

 1. **Independent Logic & Calculation Verification:** Calculated quota rates, processing batch yield estimates (\~20–25 leads per query), and completion metrics independently prior to execution.
2. **Execution & Load Testing:** Verified multi-threaded RSS parsing and SQLite write locks under active pipeline stress runs.
3. **Data Integrity Verification:** Validated exported CSV (`leads.csv`) and Excel (`leads.xlsx`) outputs for proper formatting, missing values, and deduplication logic.

