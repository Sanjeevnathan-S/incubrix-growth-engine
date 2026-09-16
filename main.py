import time
import random
import logging
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import settings
from config.settings import TARGET_LEADS_COUNT, BATCH_SIZE
from src.discovery.youtube_client import YouTubeDiscoveryClient
from src.discovery.podcast_client import PodcastDiscoveryClient
from src.filtering.geo_filter import GeographicFilter
from src.filtering.activity_filter import ActivityFilter
from src.filtering.deterministic_filter import DeterministicFilter
from src.filtering.llm_classifier import LLMSemanticClassifier
from src.enrichment.rss_parser import RSSParser
from src.enrichment.link_scraper import LinkScraper
from src.enrichment.bottleneck_check import BottleneckAnalyzer
from src.storage.db import LeadDatabase
from src.export.exporter import LeadExporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("IncuBrixPipeline")

# Threshold-based yield control for API quota optimization
MIN_PODCAST_YIELD = 50

SEARCH_QUERIES = [
    # --- Bucket 1: Music Creation, Songwriting & Audio Engineering (12) ---
    "songwriting breakdown tutorial",
    "music production workflow vlog",
    "vocal coach breakdown",
    "mixing and mastering tutorial",
    "beatmaking breakdown vlog",
    "music theory breakdown",
    "independent musician build in public",
    "acoustic guitar tutorial breakdown",
    "audio engineering masterclass",
    "sound design tutorial breakdown",
    "game audio implementation breakdown",
    "vocal tuning tutorial breakdown",

    # --- Bucket 2: Tech, AI & Software Engineering (DSA, System Design, RAG) (14) ---
    "dsa tutorial breakdown",
    "leetcode problem explanation",
    "dsa interview prep course",
    "oops concepts explained",
    "object oriented programming python",
    "system design interview prep",
    "low level design tutorial",
    "high level design breakdown",
    "rag ai architecture breakdown",
    "langchain build tutorial",
    "llm fine tuning guide",
    "full stack developer roadmap",
    "devops project breakdown",
    "tech interview live coding",

    # --- Bucket 3: Finance, Markets & Trading (10) ---
    "stock market strategy breakdown",
    "swing trading guide",
    "value investing podcast",
    "options trading breakdown",
    "macroeconomics update talk",
    "crypto market analysis vlog",
    "personal finance educator",
    "real estate investing breakdown",
    "venture capital founder interview",
    "algorithmic trading strategy breakdown",

    # --- Bucket 4: Competitive Exam & Career Prep (9) ---
    "upsc strategy breakdown",
    "upsc topper interview podcast",
    "civil services prep talk",
    "gate exam preparation guide",
    "gate cs lectures series",
    "gate ranker interview breakdown",
    "cat exam preparation strategy",
    "gre prep vocabulary guide",
    "gmat prep strategy guide",

    # --- Bucket 5: Gaming, Esports & Game Development (5) ---
    "indie game dev vlog",
    "game design analysis essay",
    "esports industry breakdown",
    "retro gaming retrospective documentary",
    "game engine tutorial breakdown",

    # --- Bucket 6: Fiction Writing, Novels & Comic Creation (12) ---
    "novel writing tutorial breakdown",
    "fantasy worldbuilding breakdown",
    "comic book creation vlog",
    "webtoon artist workflow",
    "manga creation tutorial",
    "fiction writing masterclass",
    "character writing breakdown",
    "indie author build in public",
    "light novel writing guide",
    "graphic novel process vlog",
    "storyboarding tutorial breakdown",
    "character concept art process",

    # --- Bucket 7: Science, Philosophy & Curiosities (6) ---
    "pop science breakdown essay",
    "space exploration breakdown",
    "physics intuition explained",
    "philosophy deep dive essay",
    "psychology experiment breakdown",
    "quantum computing intuition explained",

    # --- Bucket 8: Lifestyle, Travel & Creative Arts (9) ---
    "travel documentary vlog",
    "budget travel guide video",
    "street food exploration vlog",
    "culinary breakdown tutorial",
    "minimalist lifestyle vlog",
    "interior design breakdown",
    "digital art tutorial process",
    "watercolor painting breakdown",
    "sketching technique tutorial",

    # --- Bucket 9: Podcasters & Long-Form Broadcasters (12) ---
    "solo podcast host",
    "video podcast episode",
    "weekly video podcast",
    "business podcast host",
    "interview podcast host",
    "b2b podcast host",
    "tech podcast interview",
    "health and wellness podcast",
    "leadership podcast host",
    "fractional cmo podcast",
    "indie hacker podcast",
    "longform founder interview",

    # --- Bucket 10: Solopreneurs, B2B & Creator Educators (10) ---
    "build in public vlog",
    "saas founder vlog",
    "solopreneur guide",
    "copywriting breakdown",
    "digital marketing tutorial",
    "agency owner interview",
    "e-commerce breakdown",
    "cold email strategy breakdown",
    "no code workflow tutorial",
    "youtube educator breakdown",

    # --- Bucket 11: Health, Performance & Executive Coaching (6) ---
    "fitness coach breakdown",
    "executive coach breakdown",
    "high performance coach interview",
    "biohacking podcast host",
    "productivity workflows breakdown",
    "mindset coach interview",

    "b2b saas founder interview USA",
    "agency owner podcast host US",
    "executive leadership coach USA",
    "creative agency founder vlog USA",
    "fractional cmo podcast US",
    "commercial video producer vlog NYC",
    "ecommerce founder podcast interview USA",
    "high ticket sales coach breakdown USA",
    "tech founder interview UK",
    "b2b marketing podcast host UK",
    "design agency owner vlog London UK",
    "commercial video producer UK",
    "high ticket sales coach UK",
    "boutique agency owner breakdown UK",
    "fitness business owner podcast UK",
    "saas founder build in public Canada",
    "creative director process vlog Toronto Canada",
    "ecommerce agency owner Canada",
    "executive performance coach Canada",
    "b2b sales coach interview Canada",
    "independent filmmaker process vlog Canada",
    "boutique agency owner breakdown Australia",
    "business podcast host Sydney Australia",
    "solopreneur founder interview Australia",
    "fitness business coach Australia",
    "commercial photographer workflow Melbourne",
    "tech founder video podcast Australia",
    "tech startup founder interview Ireland",
    "b2b agency owner podcast Dublin Ireland",
    "leadership coach interview Ireland",
    "software agency founder breakdown Ireland",
    "digital agency founder New Zealand",
    "independent filmmaker vlog NZ",
    "business founder interview Auckland NZ",
    "consulting business owner vlog New Zealand",
    "venture backed founder podcast Singapore",
    "b2b growth consultant Singapore",
    "saas founder interview Singapore",
    "private equity operator podcast Singapore"
]

def enrich_lead(
    lead: Dict[str, Any], 
    link_scraper: LinkScraper, 
    bottleneck_analyzer: BottleneckAnalyzer
) -> Dict[str, Any]:
    """Hydrates a qualified candidate with contact details, commercial signals, and custom pitch hooks."""
    enriched = lead.copy()

    # Deep RSS parsing for podcast hosts
    if enriched.get("platform") == "podcast" and enriched.get("creator_id"):
        try:
            rss_signals = RSSParser.extract_deep_signals(enriched["creator_id"])
            emails = rss_signals.get("parsed_emails", [])
            if emails and not enriched.get("owner_email"):
                enriched["owner_email"] = emails[0]
        except Exception as e:
            logger.warning(f"RSS extraction failed for {enriched.get('creator_id')}: {e}")

    # Inspect bios & external links for monetization platforms and missing contact emails
    try:
        enrichment_data = link_scraper.extract_monetization_and_contact(
            bio_text=enriched.get("bio", ""),
            external_links=[enriched.get("website_url")] if enriched.get("website_url") else []
        )
        emails = enrichment_data.get("emails", [])
        if not enriched.get("owner_email") and emails:
            enriched["owner_email"] = emails[0]

        enriched["monetization_signals"] = enrichment_data.get("monetization_signals", [])
        enriched["external_links"] = enrichment_data.get("external_links", [])
    except Exception as e:
        logger.warning(f"Link scraping failed for {enriched.get('title', 'Unknown')}: {e}")

    # Content bottleneck & pitch hook generation
    try:
        bottlenecks = bottleneck_analyzer.analyze_creator_bottlenecks(enriched)
        enriched["bottlenecks"] = bottlenecks.get("bottlenecks", [])
        enriched["pitch_hook"] = bottlenecks.get("pitch_hook", "")
    except Exception as e:
        logger.warning(f"Bottleneck analysis failed for {enriched.get('title', 'Unknown')}: {e}")

    return enriched

def enrich_leads_parallel(
    leads: List[Dict[str, Any]], 
    link_scraper: LinkScraper, 
    bottleneck_analyzer: BottleneckAnalyzer, 
    max_workers: int = 10
) -> List[Dict[str, Any]]:
    """Runs web scraping and bottleneck checks concurrently across worker threads."""
    if not leads:
        return []
        
    enriched_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(enrich_lead, lead, link_scraper, bottleneck_analyzer)
            for lead in leads
        ]
        for future in as_completed(futures):
            try:
                enriched_results.append(future.result())
            except Exception as e:
                logger.warning(f"Parallel enrichment task failed: {e}")

    return enriched_results

def process_llm_batch(
    batch: List[Dict[str, Any]], 
    llm_classifier: LLMSemanticClassifier, 
    link_scraper: LinkScraper, 
    bottleneck_analyzer: BottleneckAnalyzer, 
    db: LeadDatabase
):
    """Executes Gemini batch classification on ambiguous candidates and saves results to DB."""
    try:
        classified_batch = llm_classifier.classify_batch(batch)
    except Exception as e:
        logger.error(f"LLM batch classification failed: {e}")
        return

    qualified_leads = []

    for lead in classified_batch:
        if not lead.get("is_original_creator", False):
            db.save_lead(lead, status="REJECTED_INVALID_ACCOUNT")
        else:
            qualified_leads.append(lead)

    # Parallel enrichment for qualified candidates
    if qualified_leads:
        enriched_leads = enrich_leads_parallel(qualified_leads, link_scraper, bottleneck_analyzer, max_workers=10)
        
        # Save to SQLite sequentially on Main Thread
        for enriched in enriched_leads:
            db.save_lead(enriched, status="QUALIFIED")
            logger.info(
                f"QUALIFIED LEAD ({db.get_qualified_lead_count()}/{TARGET_LEADS_COUNT}) "
                f"[{enriched.get('country', 'UNK')}]: {enriched.get('title', 'Unknown Title')}"
            )

def run_pipeline():
    db = LeadDatabase()
    yt_client = YouTubeDiscoveryClient()
    podcast_client = PodcastDiscoveryClient()
    
    geo_filter = GeographicFilter()
    activity_filter = ActivityFilter()
    deterministic_filter = DeterministicFilter()
    llm_classifier = LLMSemanticClassifier()
    
    link_scraper = LinkScraper()
    bottleneck_analyzer = BottleneckAnalyzer()

    logger.info("Starting IncuBrix Automated Discovery Pipeline...")
    prefiltered_queue = []

    try:
        for query in SEARCH_QUERIES:
            current_count = db.get_qualified_lead_count()
            if current_count >= TARGET_LEADS_COUNT:
                logger.info(f"Target count of {TARGET_LEADS_COUNT} qualified leads reached!")
                break

            if not db.should_scrape_query(query=query, country="GLOBAL", ttl_days=30):
                logger.info(f"Skipping query '{query}' — active TTL (searched < 30 days ago).")
                continue

            logger.info(f"Executing discovery for query: '{query}' | Current Qualified Count: {current_count}")

            yt_candidates = []
            podcast_candidates = []

            # 1. Podcast Discovery (Zero Quota Cost — Always Executed First)
            try:
                podcast_candidates = podcast_client.search_podcasts(query=query, db=db, limit_per_country=50)
            except Exception as e:
                logger.error(f"Podcast discovery failed for query '{query}': {e}")

            # 2. Yield-Driven YouTube Discovery (Triggered only if podcast yield < MIN_PODCAST_YIELD)
            podcast_yield = len(podcast_candidates)
            if podcast_yield < MIN_PODCAST_YIELD:
                logger.info(
                    f"Podcast yield ({podcast_yield}) below threshold ({MIN_PODCAST_YIELD}) for query '{query}'. "
                    f"Triggering YouTube fallback discovery..."
                )
                try:
                    yt_candidates = yt_client.search_creators(query=query, db=db, max_results_per_country=20)
                except Exception as e:
                    logger.error(f"YouTube discovery failed for query '{query}': {e}")
            else:
                logger.info(
                    f"Skipping YouTube discovery for query '{query}' "
                    f"(Podcast yield of {podcast_yield} met/exceeded threshold of {MIN_PODCAST_YIELD}, preserving API quota)."
                )

            # Combine candidates without dropping leads from either platform
            candidates = podcast_candidates + yt_candidates

            if not candidates:
                db.record_search(query=query, country="GLOBAL", scraped_count=0)
                continue

            all_candidate_ids = [c["creator_id"] for c in candidates if c.get("creator_id")]
            unseen_ids = set(db.filter_unseen_channel_ids(all_candidate_ids))
            seen_in_batch = set()

            for candidate in candidates:
                creator_id = candidate.get("creator_id")
                if not creator_id or creator_id in seen_in_batch:
                    continue
                
                seen_in_batch.add(creator_id)

                # Dynamic Update for existing leads
                if creator_id not in unseen_ids:
                    recent_videos = (
                        candidate.get("recent_videos") 
                        or candidate.get("recent_episodes") 
                        or candidate.get("recent_content")
                    )
                    db.update_lead_dynamic_fields(
                        creator_id=creator_id,
                        recent_publish_dates=candidate.get("recent_publish_dates"),
                        recent_videos=recent_videos
                    )
                    continue

                # Stage 1: Geographic Pre-Filter
                if not geo_filter.is_valid_geo(candidate):
                    db.save_lead(candidate, status="REJECTED_GEO")
                    continue

                # Stage 2: Activity Density Pre-Filter
                if not activity_filter.is_active_creator(candidate):
                    db.save_lead(candidate, status="REJECTED_INACTIVE")
                    continue

                # Stage 3: Deterministic Rule Audit
                det_result = deterministic_filter.evaluate(candidate)

                if det_result is not None:
                    candidate.update(det_result)
                    if det_result.get("is_original_creator", False):
                        enriched = enrich_lead(candidate, link_scraper, bottleneck_analyzer)
                        db.save_lead(enriched, status="QUALIFIED")
                        current_count = db.get_qualified_lead_count()
                        logger.info(
                            f"AUTO-PASSED LEAD ({current_count}/{TARGET_LEADS_COUNT}) "
                            f"[{candidate.get('country', 'UNK')}]: {candidate.get('title', 'Unknown Title')}"
                        )
                    else:
                        db.save_lead(candidate, status="REJECTED_AUTO")
                    
                    if current_count >= TARGET_LEADS_COUNT:
                        break
                    continue

                # Stage 4: Queue for Gemini Batch Processing
                prefiltered_queue.append(candidate)

                if len(prefiltered_queue) >= BATCH_SIZE:
                    process_llm_batch(prefiltered_queue, llm_classifier, link_scraper, bottleneck_analyzer, db)
                    prefiltered_queue.clear()
                    time.sleep(5.5)  # 15 RPM Free Tier compliance

                    current_count = db.get_qualified_lead_count()
                    if current_count >= TARGET_LEADS_COUNT:
                        break

            # Flush any remaining candidates from this query batch into DB before caching search query
            if prefiltered_queue and db.get_qualified_lead_count() < TARGET_LEADS_COUNT:
                process_llm_batch(prefiltered_queue, llm_classifier, link_scraper, bottleneck_analyzer, db)
                prefiltered_queue.clear()

            # Record search query in DB NOW (strictly after discovery -> filter -> storage complete)
            db.record_search(query=query, country="GLOBAL", scraped_count=len(candidates))

            if db.get_qualified_lead_count() >= TARGET_LEADS_COUNT:
                logger.info(f"Target count reached during query '{query}'. Stopping pipeline loop.")
                break

    except KeyboardInterrupt:
        logger.warning("\nPipeline manually stopped by user (Ctrl+C). Initiating emergency export...")
    except Exception as e:
        logger.error(f"Pipeline execution hit an unexpected error: {e}", exc_info=True)
    finally:
        # Stage 5: Emergency & Final Workbook Export
        logger.info("Applying database window functions for 60% country ratio ceiling...")
        qualified_leads = db.export_all_qualified(target_limit=TARGET_LEADS_COUNT, max_country_ratio=0.60)
        if qualified_leads:
            LeadExporter.export_to_csv_and_excel(qualified_leads)
            logger.info(f"Export sync complete. {len(qualified_leads)} qualified leads written to disk.")
        else:
            logger.warning("No qualified leads found to export.")

if __name__ == "__main__":
    run_pipeline()