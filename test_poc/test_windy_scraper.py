

import asyncio
import json
import sys

from leoai.data_scraper.windy_scraper import get_windy_forecast_raw_data
from tests.test_ai_prediction import extract_weather_info_from_text

async def process_weather_data(lat: float, lon: float, limit_days: int = 5):
    
    text_filename, screenshot_filename = await get_windy_forecast_raw_data(lat,lon)
    print(text_filename)
    
    #text_filename = 'data_windy/windy_11.729_109.536_20251203_150436.txt'
    weather_info = extract_weather_info_from_text(f"./{text_filename}", limit_days)

    #  Pretty-print
    # readable1 = json.dumps(data1, indent=2, ensure_ascii=False)
    # print(readable1)
    readable = json.dumps(weather_info, indent=2, ensure_ascii=False)
    print(readable)
    print(screenshot_filename)
