# External Sources & Attributions

 This document details all external APIs, models, open-source libraries, and data sources utilized within the **Incrubrix: Growth Assessment** pipeline.

---

 ## 1\. Machine Learning & LLM Services

 - **Google Gemini API**
  - **Provider:** Google AI
  - **Usage:** Qualification classification of discovered creators via available free-tier endpoints.
  - **Rotation Engine:** Multi-key failover handling across 3 distinct API keys to mitigate rate limits (`429`).
  - **License / Terms:** Subject to Google AI Terms of Service.

---

 ## 2\. Discovery APIs & Data Sources

 - **Apple Podcasts Search API**
  - **Endpoint:** `https://itunes.apple.com/search`
  - **Usage:** Initial podcast creator discovery across 7 target geographical regions (`US`, `CA`, `GB`, `IE`, `AU`, `NZ`, `SG`).
  - **License / Terms:** Subject to Apple's applicable services and API terms.
- **YouTube Data API v3**
  - **Provider:** Google Developers
  - **Usage:** Secondary channel and video metadata discovery.
  - **Quota Management:** Automatically bypassed when configured API quota limits are exhausted.
- **YouTube Channel RSS Feeds**
  - **Endpoint:** `https://www.youtube.com/feeds/videos.xml?channel_id=`
  - **Usage:** Public XML feed extraction for recent uploads and video metadata without YouTube Data API quota consumption.

---

 ## 3\. Open-Source Python Libraries

 | Library | Primary Use Case | License |
| --- | --- | --- |
| **`scrapetube`** | Light zero-quota YouTube channel search discovery | MIT |
| **`feedparser`** | Parsing RSS/Atom feeds for episode/video metadata | BSD 2-Clause |
| **`beautifulsoup4`** | HTML extraction for landing-page email regex scraping | MIT |
| **`requests`** | Synchronous HTTP communication for web requests | Apache 2.0 |
| **`pandas` / `openpyxl`** | Structuring and exporting qualified leads to CSV and Excel | BSD / MIT |
| **`sqlite3`** | Standard-library embedded database engine for TTL caching | Public Domain |

---

 ## 4\. Software Dependencies & Built-in Modules

 - **Python Standard Library:**
  - `os`
  - `re`
  - `time`
  - `json`
  - `logging`
  - `socket`
  - `sqlite3`
  - `concurrent.futures`
  - `typing`