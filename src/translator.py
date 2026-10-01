from deep_translator import GoogleTranslator, MyMemoryTranslator
import logging

logger = logging.getLogger(__name__)

ISO_TO_NAME = {
    'hi': 'hindi', 'es': 'spanish', 'fr': 'french', 'de': 'german',
    'it': 'italian', 'ja': 'japanese', 'ko': 'korean', 'pt': 'portuguese',
    'ru': 'russian', 'zh': 'chinese simplified', 'ar': 'arabic', 'bn': 'bengali',
    'ta': 'tamil india', 'te': 'telugu', 'mr': 'marathi', 'gu': 'gujarati',
    'ur': 'urdu', 'pa': 'punjabi', 'nl': 'dutch', 'tr': 'turkish'
}

_GOOGLE_AVAILABLE = True

def translate_text(text: str, source_lang: str = 'auto', target_lang: str = 'en') -> str:
    """
    Translates text to the target language.
    """
    global _GOOGLE_AVAILABLE
    if not text or not text.strip():
        return ""
        
    s_clean = source_lang.lower().strip() if source_lang else 'auto'
    t_clean = target_lang.lower().strip() if target_lang else 'en'
    
    if s_clean in [t_clean, 'en', 'english'] and t_clean in ['en', 'english']:
        return text

    if _GOOGLE_AVAILABLE:
        try:
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            return translator.translate(text)
        except Exception as e:
            logger.warning(f"GoogleTranslator unavailable ({e}). Switching to MyMemoryTranslator.")
            _GOOGLE_AVAILABLE = False

    # Fallback to MyMemoryTranslator
    try:
        source_name = ISO_TO_NAME.get(s_clean, s_clean)
        target_name = 'english' if t_clean in ['en', 'english'] else ISO_TO_NAME.get(t_clean, t_clean)
        translator = MyMemoryTranslator(source=source_name, target=target_name)
        res = translator.translate(text)
        return res if res else text
    except Exception as e2:
        logger.warning(f"Fallback translation failed: {e2}")
        return text
