import os
import json
import time
import logging
from typing import List, Dict, Any, Union

# SDK detection
try:
    from google import genai
    from google.genai import types
    USING_NEW_SDK = True
except ImportError:
    import google.generativeai as genai
    USING_NEW_SDK = False

try:
    from google.api_core.exceptions import ResourceExhausted, GoogleAPIError, NotFound
except ImportError:
    ResourceExhausted = Exception
    GoogleAPIError = Exception
    NotFound = Exception

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT_TEMPLATE = """
You are an expert lead qualification auditor for Incubrix. Analyze the following batch of YouTube/Podcast candidate metadata.
Determine whether each candidate is an ORIGINAL CREATOR (an authentic individual creator, founder, host, or domain expert producing original content) or an INVALID ACCOUNT (fan page, clip channel, content aggregator, corporate channel, daily reuploader, or bot).

Requirement criteria:
1. "is_original_creator": true if the channel/podcast is run by the original host/creator/founder producing original show content.
2. "confidence": float between 0.0 and 1.0 indicating confidence in this classification.
3. "account_category": choice of ["individual_creator", "podcast_host", "company_media", "fan_page_aggregator", "clip_channel"]
4. "reason": concise explanation for the decision.

Input Candidates:
{candidates_json}

Return ONLY a valid JSON array of objects with keys: "item_id", "is_original_creator", "confidence", "account_category", "reason". Do not wrap in markdown quotes.
"""

class LLMSemanticClassifier:
    def __init__(
        self, 
        api_key: Union[str, List[str]] = None, 
        model_name: Union[str, List[str]] = None
    ):
        raw_keys = api_key or os.getenv("GEMINI_API_KEY", "")
        if isinstance(raw_keys, str):
            self.api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        elif isinstance(raw_keys, list):
            self.api_keys = [str(k).strip() for k in raw_keys if str(k).strip()]
        else:
            self.api_keys = []

        raw_models = model_name or os.getenv("LLM_MODEL_NAME", "gemini-1.5-flash,gemini-2.0-flash,gemini-1.5-flash-8b")
        if isinstance(raw_models, str):
            self.models = [m.strip() for m in raw_models.split(",") if m.strip()]
        elif isinstance(raw_models, list):
            self.models = [str(m).strip() for m in raw_models if str(m).strip()]
        else:
            self.models = ["gemini-1.5-flash"]

        self.current_key_index = 0
        self.current_model_index = 0

        if not self.api_keys:
            logger.error("No Gemini API keys found in GEMINI_API_KEY environment variable.")
        else:
            self._log_active_state()

    def _get_active_key(self) -> str:
        if not self.api_keys:
            return ""
        return self.api_keys[self.current_key_index]

    def _get_active_model(self) -> str:
        if not self.models:
            return "gemini-1.5-flash"
        return self.models[self.current_model_index]

    def _log_active_state(self):
        active_key = self._get_active_key()
        masked = f"{active_key[:6]}...{active_key[-4:]}" if len(active_key) > 10 else "***"
        logger.info(
            f"Active Config -> Key #{self.current_key_index + 1}/{len(self.api_keys)} ({masked}) | "
            f"Model #{self.current_model_index + 1}/{len(self.models)} ('{self._get_active_model()}')"
        )

    def _rotate_key(self) -> bool:
        if len(self.api_keys) <= 1:
            return False
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        logger.warning(f"Rotating to Gemini API Key #{self.current_key_index + 1}/{len(self.api_keys)}...")
        time.sleep(1)
        self._log_active_state()
        return True

    def _rotate_model(self) -> bool:
        if len(self.models) <= 1:
            return False
        self.current_model_index = (self.current_model_index + 1) % len(self.models)
        logger.warning(f"Switching Model -> #{self.current_model_index + 1}/{len(self.models)}: '{self._get_active_model()}'")
        time.sleep(1)
        self._log_active_state()
        return True

    def _generate_content_with_failover(self, prompt: str) -> str:
        max_attempts = (len(self.api_keys) * len(self.models)) + 2

        for attempt in range(max_attempts):
            active_key = self._get_active_key()
            active_model = self._get_active_model()

            if not active_key:
                raise RuntimeError("No valid Gemini API key available.")

            try:
                if USING_NEW_SDK:
                    client = genai.Client(api_key=active_key)
                    response = client.models.generate_content(
                        model=active_model,
                        contents=prompt
                    )
                    return response.text
                else:
                    genai.configure(api_key=active_key)
                    model = genai.GenerativeModel(active_model)
                    response = model.generate_content(prompt)
                    return response.text

            except Exception as e:
                err_msg = str(e).lower()
                
                is_404 = isinstance(e, NotFound) or "404" in err_msg or "not found" in err_msg or "not_found" in err_msg
                is_quota = (
                    isinstance(e, ResourceExhausted) 
                    or "429" in err_msg 
                    or "quota" in err_msg 
                    or "resourceexhausted" in err_msg
                )

                if is_404:
                    logger.warning(f"Model '{active_model}' returned 404 (Not Found). Initiating model rotation...")
                    if not self._rotate_model():
                        raise RuntimeError(f"Configured model '{active_model}' not found and no alternative models available.")
                
                elif is_quota:
                    logger.warning(f"Key #{self.current_key_index + 1} quota exhausted on model '{active_model}'.")
                    # Try rotating API key first
                    if not self._rotate_key():
                        # If keys are exhausted, rotate model and reset key loop
                        logger.warning("All keys exhausted for current model. Rotating model fallback...")
                        if not self._rotate_model():
                            logger.info("All keys and models exhausted. Sleeping 15s before retry...")
                            time.sleep(15)
                else:
                    logger.error(f"Gemini API Execution Error on '{active_model}': {e}")
                    if attempt == max_attempts - 1:
                        raise e
                    time.sleep(2)

        raise RuntimeError("Failed to complete Gemini request after all key and model rotation attempts.")

    def classify_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not batch:
            return []

        payload = []
        for idx, candidate in enumerate(batch):
            payload.append({
                "item_id": idx,
                "title": candidate.get("title", ""),
                "handle_or_artist": candidate.get("handle_or_artist", ""),
                "bio": candidate.get("bio", ""),
                "recent_titles": candidate.get("recent_titles", [])[:3]
            })

        prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(
            candidates_json=json.dumps(payload, indent=2)
        )

        try:
            raw_text = self._generate_content_with_failover(prompt)

            cleaned_text = raw_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]

            results = json.loads(cleaned_text.strip())
            
            output_batch = []
            for idx, candidate in enumerate(batch):
                item = candidate.copy()
                llm_eval = next((r for r in results if r.get("item_id") == idx), None)

                if llm_eval:
                    confidence = float(llm_eval.get("confidence", 0.0))
                    is_original = bool(llm_eval.get("is_original_creator", False))
                    
                    if is_original and confidence < 0.85:
                        is_original = False
                        reason = f"Rejected: Confidence < 0.85 ({confidence:.2f}) - {llm_eval.get('reason')}"
                    else:
                        reason = llm_eval.get("reason", "")

                    item.update({
                        "is_original_creator": is_original,
                        "confidence": confidence,
                        "account_category": llm_eval.get("account_category", "unknown"),
                        "reason": reason
                    })
                else:
                    item.update({
                        "is_original_creator": False,
                        "confidence": 0.0,
                        "account_category": "unknown",
                        "reason": "Missing from LLM response payload"
                    })

                output_batch.append(item)

            return output_batch

        except Exception as e:
            logger.error(f"Gemini batch classification failure: {e}")
            
            fallback_list = []
            for candidate in batch:
                item = candidate.copy()
                item.update({
                    "is_original_creator": False,
                    "confidence": 0.0,
                    "account_category": "unknown",
                    "reason": f"Classification failed due to API error: {str(e)}"
                })
                fallback_list.append(item)

            return fallback_list