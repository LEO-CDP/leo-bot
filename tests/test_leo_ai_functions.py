# run_all_units.py

import asyncio
import sys
from main_config import setup_logging
from test_poc.test_windy_scraper import process_weather_data
from tests.test_ai_prediction import extract_geolocation_from_image, extract_weather_info_from_text, prepare_image_bytes
import json

setup_logging()


# 1. Định nghĩa đường dẫn file PNG gốc
input_file_path = "/home/thomas/Pictures/Screenshots/meaning-of-saigon-2_1702214121.jpeg"


def run_prepare_image_bytes_jpeg():
    img_bytes, meta = prepare_image_bytes(input_file_path)
    assert meta["converted"] is False
    assert len(img_bytes) > 0


def run_extract_json_from_image():
    output = extract_geolocation_from_image(
        input_file_path,
        "Extract hourly raw data and convert to JSON"
    )
    print(output)
    assert output["result"]["city"] == "Ho Chi Minh City"
    assert output["result"]["location_name"] == "Notre Dame Cathedral Basilica of Saigon"


def run_extract_weather_info_from_text():
    lat = float(sys.argv[1])
    lon = float(sys.argv[2])
    asyncio.run(process_weather_data(lat, lon, 2))


if __name__ == "__main__":
    # run_prepare_image_bytes_jpeg()
    # run_extract_json_from_image()
    run_extract_weather_info_from_text()
    print("All unit tasks finished.")
