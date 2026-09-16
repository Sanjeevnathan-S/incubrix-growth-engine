import os
import json
import logging
import pandas as pd
from typing import List, Dict, Any
from config.settings import OUTPUT_CSV_PATH

logger = logging.getLogger(__name__)


class LeadExporter:
    APPROVED_TIER1_COUNTRIES = {"US", "CA", "GB", "UK", "IE", "AU", "NZ", "SG"}

    @staticmethod
    def _parse_json_list(val: Any) -> str:
        """Safely converts JSON string representations or Python sequences into clean comma-separated strings."""
        if not val:
            return ""
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return ", ".join(str(item) for item in parsed if item)
                return str(parsed)
            except (json.JSONDecodeError, TypeError):
                return val
        if isinstance(val, (list, set, tuple)):
            return ", ".join(str(item) for item in val if item)
        return str(val)

    @classmethod
    def export_to_csv_and_excel(
        cls, 
        leads: List[Dict[str, Any]], 
        csv_path: str = None,
        max_country_ratio: float = 0.60
    ) -> None:
        if not leads:
            logger.warning("No qualified leads found to export.")
            return

        target_csv = csv_path or OUTPUT_CSV_PATH
        base_path, _ = os.path.splitext(target_csv)
        target_excel = f"{base_path}.xlsx"
        
        dir_name = os.path.dirname(target_csv)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        # 1. Sort by confidence score descending
        sorted_leads = sorted(
            leads, 
            key=lambda x: x.get("confidence_score") if x.get("confidence_score") is not None else x.get("confidence", 0.0), 
            reverse=True
        )

        # 2. Enforce Country Ratio Cap (<= max_country_ratio)
        total_leads = len(sorted_leads)
        max_per_country = max(1, int(total_leads * max_country_ratio)) if max_country_ratio else float("inf")
        
        country_counts: Dict[str, int] = {}
        filtered_leads = []

        for lead in sorted_leads:
            country = (lead.get("country") or "UNKNOWN").upper()
            current_count = country_counts.get(country, 0)

            if current_count < max_per_country:
                filtered_leads.append(lead)
                country_counts[country] = current_count + 1
            else:
                logger.debug(f"Skipping lead '{lead.get('creator_id')}' from {country} — reached country cap ({max_per_country}).")

        # 3. Build Export Records & Assign Priority Tags
        cleaned_leads = []
        for idx, lead in enumerate(filtered_leads):
            bio = lead.get("bio") or ""
            formatted_bio = bio[:250] + "..." if len(bio) > 250 else bio
            confidence = (
                lead.get("confidence_score") 
                if lead.get("confidence_score") is not None 
                else lead.get("confidence", 0.0)
            )

            # Assign Priority A to top 25 leads of the final filtered set
            priority_tag = "Priority A" if idx < 25 else "Standard"

            # Fallback lookup for commercial evidence
            comm_evidence = (
                lead.get("monetization_signals") 
                or lead.get("external_links") 
                or lead.get("commercial_evidence")
            )

            cleaned_leads.append({
                "Priority Rank": priority_tag,
                "Platform": str(lead.get("platform", "")).upper(),
                "Creator ID / Feed": lead.get("creator_id", ""),
                "Channel / Show Title": lead.get("title", ""),
                "Handle / Host": lead.get("handle_or_artist", ""),
                "Country": lead.get("country", ""),
                "Verified Contact Email / Route": lead.get("owner_email", ""),
                "Website / Profile URL": lead.get("website_url", ""),
                "Account Category": lead.get("account_category", ""),
                "Confidence Score": confidence,
                "Commercial Evidence Links": cls._parse_json_list(comm_evidence),
                "Identified Bottlenecks": cls._parse_json_list(lead.get("bottlenecks")),
                "Custom Pitch Hook": lead.get("pitch_hook", ""),
                "Qualification Reason": lead.get("qualification_reason") or lead.get("reason", ""),
                "Bio Description": formatted_bio
            })

        df = pd.DataFrame(cleaned_leads)
        
        # Export CSV with UTF-8 BOM encoding
        df.to_csv(target_csv, index=False, encoding="utf-8-sig")
        logger.info(f"Successfully exported {len(cleaned_leads)} leads to {target_csv}")

        # Export Excel workbook with column width formatting
        try:
            with pd.ExcelWriter(target_excel, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="IncuBrix Leads")
                worksheet = writer.sheets["IncuBrix Leads"]
                
                for col in worksheet.columns:
                    max_len = max(len(str(cell.value or '')) for cell in col)
                    col_letter = col[0].column_letter
                    worksheet.column_dimensions[col_letter].width = min(max(max_len + 3, 14), 50)
                    
            logger.info(f"Successfully exported {len(cleaned_leads)} leads to {target_excel}")
        except Exception as e:
            logger.error(f"Excel export error: {e}")