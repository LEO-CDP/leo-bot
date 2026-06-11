

import json
import datetime


def build_weather_prompt(json_schema, cleaned_text, limit_days: int = 0, reference_date_str: str = None):
    """
    Generates a prompt for extracting weather data with strict date range filtering.
    
    Args:
        json_schema (str): The target JSON structure.
        cleaned_text (str): The HTML table content.
        reference_date_str (str): The ISO timestamp of the data source (e.g., "2025-12-03").
        limit_days (int): Number of days to include relative to the start date. 
                          0 = include all. 1 = start date only.
    """
    
    if reference_date_str is None:
        # Use only the date part (YYYY-MM-DD) for consistency in the prompt instructions
        reference_date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    # Construct the limit instruction dynamically
    limit_instruction = ""
    if limit_days > 0:
        limit_instruction = f"""
        5) DATE FILTERING (CRITICAL):
        - Reference Start Date: {reference_date_str}
        - You must ONLY include data columns where the calculated date is strictly less than {limit_days} days after the Start Date.
        - Logic: If (Column_Date - Start_Date) >= {limit_days} days, DISCARD the column.
        - Example: If limit_days is 1, keep ONLY the columns belonging to the Start Date.
        """
    else:
        limit_instruction = "5) DATE FILTERING: Include all days found in the table."

    prompt_text = f"""
    You are a precise HTML-to-JSON parser for weather data.
    
    # CONTEXT
        - Reference Timestamp: {reference_date_str}
        - The HTML table headers contain only Day Name and Day Number (e.g., "Wednesday 3").
        - You must map "Wednesday 3" to the Reference Timestamp provided above.
        - If the day number resets (e.g., 30 -> 1), increment the month logic automatically.

    # INSTRUCTIONS
    1) Parse the HTML Table strictly:
        - <tr> with class 'tr--hour' -> Hour (0-23)
        - <tr> with class 'tr--icon' -> Image URL (extract from srcset or src)
        - <tr> with class 'tr--temp' -> Temperature (int, strip symbols)
        - <tr> with class 'tr--rain' -> Rain (float, blank = 0.0)
        - <tr> with class 'tr--wind' -> Wind Speed (int, knots)
        - <tr> with class 'tr--gust' -> Wind Gust (int, knots)
        - <tr> with class 'tr--windDir' -> Wind Direction (int, extract degrees from CSS 'transform: rotate(Xdeg)')

    2) Column Alignment:
        - The table is column-aligned. Index 0 in 'tr--hour' corresponds to Index 0 in 'tr--temp', etc.
        - A Day Header (colspan) applies to all columns beneath it until the next header.

    3) Data formatting:
        - Return valid JSON only.
        - Null values for missing non-numeric data.
        - 0 for missing numeric data (rain, etc).

    {limit_instruction}
    
    5) DATA INTEGRITY & OUTPUT RULES (Strict):
        - Preserve column order EXACTLY; do not reorder, merge, or infer data.
        - **Forbidden:** No commentary, markdown, or alternative structures. Never hallucinate values (no invented hours, dates, or icons).
        - Produce ONLY valid JSON that strictly adheres to the provided schema:
        {json_schema}

    # RAW HTML INPUT
    ---------------------------------------------------
    {cleaned_text}
    ---------------------------------------------------
    """
    return prompt_text


# ------------------------------
# Inject weather classification into JSON
# ------------------------------
def enrich_weather_forecast(text: str) -> dict:
    weather_info = json.loads(text)

    if "forecast_days" not in weather_info:
        raise ValueError("Missing key: 'forecast_days' at root JSON level")

    for day in weather_info["forecast_days"]:
        hours = day.get("hours", [])
        for hour in hours:

            temp = hour.get("temperature_c")
            rain = hour.get("rain_mm")
            kt = hour.get("wind_kt")
            gust_kt = hour.get("wind_gust_kt")

            # --- Add enriched info ---
            if temp is not None:
                hour["temperature_info"] = classify_temperature(float(temp))

            if rain is not None:
                hour["rain_info"] = classify_rain(float(rain))

            if kt is not None:
                hour["wind_info"] = classify_knots(float(kt))

            if gust_kt is not None:
                hour["wind_gust_info"] = classify_knots(float(gust_kt))

            # --- Remove raw data to avoid duplicate ---
            hour.pop("wind_kt", None)
            hour.pop("wind_gust_kt", None)
            hour.pop("rain_mm", None)
            hour.pop("temperature_c", None)

    return weather_info


def knots_to_mps(knots: float) -> float:
    """
    Convert wind speed from knots (kt) to meters per second (m/s).

    1 knot = 0.514444 m/s (exact by definition)
    Handles None, negative values, and non-numeric input safely.
    """
    if knots is None:
        return 0.0

    try:
        value = float(knots)
    except (ValueError, TypeError):
        return 0.0

    # Guardrail: wind cannot be negative
    if value < 0:
        value = 0.0

    return round(value * 0.514444, 3)


def wind_label_from_mps(mps: float) -> dict:
    """
    Classify wind speed (m/s) into Beaufort-like categories.
    Includes English/Vietnamese labels and a storm-alert severity level.
    """

    # Continuous ranges — no gaps
    ranges = [
        (0,    0.2,   "Calm",             "Lặng gió",           0),
        (0.3,  1.6,   "Light Air",        "Gió nhẹ",            0),
        (1.6,  3.3,   "Light Breeze",     "Gió hiu hiu",        0),
        (3.3,  5.4,   "Gentle Breeze",    "Gió nhẹ vừa",        0),
        (5.5,  7.9,   "Moderate Breeze",  "Gió trung bình",     0),
        (8.0,  10.7,  "Fresh Breeze",     "Gió mạnh vừa",       1),
        (10.7, 13.8,  "Strong Breeze",    "Gió mạnh",           1),
        (13.8, 17.1,  "Near Gale",        "Gió gần cấp giật",   1),
        (17.1, 20.7,  "Gale",             "Gió giật mạnh",      2),
        (20.7, 24.4,  "Strong Gale",      "Gió giật rất mạnh",  2),
        (24.4, 28.4,  "Storm",            "Bão",                3),
        (28.4, 32.6,  "Violent Storm",    "Bão dữ dội",         4),
        (32.6, float("inf"),
         "Hurricane",            "Cuồng phong",         5),
    ]

    for low, high, en, vi, alert in ranges:
        if low <= mps <= high:
            return {
                "label_en": en,
                "label_vi": vi,
                "alert_level": alert,
                "alert_text_en": alert_level_to_text(alert, lang="en"),
                "alert_text_vi": alert_level_to_text(alert, lang="vi")
            }

    return {
        "label_en": "Unknown",
        "label_vi": "Không xác định",
        "alert_level": 0,
        "alert_text_en": "Unknown",
        "alert_text_vi": "Không xác định"
    }


def alert_level_to_text(alert: int, lang: str = "en") -> str:
    alert_en = {
        0: "Normal",
        1: "Windy",
        2: "Strong Winds",
        3: "Storm Warning",
        4: "Severe Storm",
        5: "Extreme Hurricane"
    }

    alert_vi = {
        0: "Bình thường",
        1: "Gió mạnh",
        2: "Gió rất mạnh",
        3: "Cảnh báo bão",
        4: "Bão nguy hiểm",
        5: "Siêu bão cực mạnh"
    }

    return alert_en.get(alert) if lang == "en" else alert_vi.get(alert)


def classify_knots(knots: float) -> dict:
    """
    Convert kt → m/s and return bilingual wind classification.
    """
    mps = knots_to_mps(knots)
    label_info = wind_label_from_mps(mps)

    return {
        "knots": knots,
        "mps": mps,
        "label_en": label_info["label_en"],
        "label_vi": label_info["label_vi"],
        "alert_level": label_info["alert_level"],
        "alert_text_en": label_info["alert_text_en"],
        "alert_text_vi": label_info["alert_text_vi"],
    }


def classify_temperature(temp_c: float) -> dict:
    """
    Classify temperature with English/Vietnamese labels and heat alert level.
    Alert level scale:
      0 = normal
      1 = warm
      2 = hot
      3 = very hot / dangerous heat
    """
    if temp_c is None:
        return None

    ranges = [
        (-50, 12,   "Cold",          "Lạnh",             0),
        (12, 18,    "Cool",          "Mát",              0),
        (18, 27,    "Warm",          "Ấm",               1),
        (27, 33,    "Hot",           "Nóng",             2),
        (33, 60,    "Very Hot",      "Rất nóng",         3),
    ]

    for low, high, en, vi, alert in ranges:
        if low <= temp_c <= high:
            return {
                "temperature_c": temp_c,
                "label_en": en,
                "label_vi": vi,
                "alert_level": alert
            }

    # fallback
    return {
        "temperature_c": temp_c,
        "label_en": "Unknown",
        "label_vi": "Không xác định",
        "alert_level": 0
    }


def classify_rain(rain_mm: float) -> dict:
    """
    Classify rain intensity (mm/hr).
    Alert scale:
      0 = none/light
      1 = moderate
      2 = heavy
      3 = very heavy / dangerous
    """

    if rain_mm is None:
        rain_mm = 0.0

    ranges = [
        (0,   0.2,  "No Rain",        "Không mưa",          0),
        (0.2, 2.0,  "Light Rain",     "Mưa nhẹ",            0),
        (2.0, 10.0, "Moderate Rain",  "Mưa vừa",            1),
        (10.0, 25.0, "Heavy Rain",     "Mưa to",             2),
        (25.0, 9999, "Very Heavy Rain", "Mưa rất to",         3),
    ]

    for low, high, en, vi, alert in ranges:
        if low <= rain_mm <= high:
            return {
                "rain_mm": rain_mm,
                "label_en": en,
                "label_vi": vi,
                "alert_level": alert
            }

    return {
        "rain_mm": rain_mm,
        "label_en": "Unknown",
        "label_vi": "Không xác định",
        "alert_level": 0
    }
