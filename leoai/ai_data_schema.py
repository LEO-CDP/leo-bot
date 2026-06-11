import logging
# Assuming this import structure for the Google Generative AI SDK Schema type
from google.genai.types import Schema

logger = logging.getLogger(__name__)


def build_weather_schema() -> Schema:
    """
    Weather schema optimized for LLM extraction from messy Windy HTML/Markdown.
    More explicit descriptions reduce hallucination and enforce correct parsing.
    """

    try:
        return Schema(
            type="object",
            description=(
                "Structured weather forecast extracted from Windy.com markup. "
                "The model must normalize HTML/Markdown table values exactly as shown, "
                "including empty cells converted to numeric zero where appropriate."
            ),
            properties={
                "location": Schema(
                    type="object",
                    description="Recognized location metadata.",
                    properties={
                        "name": Schema(type="string", description="Name of the detected location."),
                        "city": Schema(type="string", description="City name if available, otherwise 'Unknown'."),
                        "country": Schema(type="string", description="Country name or 'Unknown'."),
                        "latitude": Schema(
                            type="string",
                            description=(
                                "Latitude in decimal degrees (from Windy URL or context). "
                                "Return exact value as string, do not guess."
                            )
                        ),
                        "longitude": Schema(
                            type="string",
                            description=(
                                'Longitude in decimal degrees. '
                                'Return as string to avoid float rounding differences.'
                            )
                        ),
                        "time_zone": Schema(
                            type="string",
                            description="IANA timezone if inferable, otherwise 'Unknown'."
                        )
                    },
                    required=["name", "city", "country", "latitude", "longitude", "time_zone"]
                ),

                "metadata": Schema(
                    type="object",
                    description="Metadata describing parsing and source information.",
                    properties={
                        "data_source": Schema(type="string", description="Fixed: 'Windy.com'."),
                        "model_source": Schema(
                            type="string",
                            description="Weather model if explicitly visible. Otherwise return 'Unknown'."
                        ),
                        "source_url": Schema(
                            type="string",
                            description="The raw Windy.com URL from the markdown section."
                        ),
                        "updated_at": Schema(
                            type="string",
                            description="Timestamp for when the data was captured."
                        )
                    },
                    required=["data_source", "model_source", "updated_at"]
                ),

                "forecast_days": Schema(
                    type="array",
                    description=(
                        "List of daily forecasts. "
                        "LLM must map each vertical column in the table to a correct day/date."
                    ),
                    items=Schema(
                        type="object",
                        properties={
                            "date": Schema(
                                type="string",
                                description=(
                                    "Date in YYYY-MM-DD. "
                                    "Model must infer day alignment from markdown headings (e.g. 'Sunday 30'). "
                                    "Convert day-of-month into full ISO date based on provided timestamp."
                                )
                            ),
                            "hours": Schema(
                                type="array",
                                description="Hourly forecast extracted column-by-column.",
                                items=Schema(
                                    type="object",
                                    description="Weather entry for a specific hour.",
                                    properties={
                                        "time_hour": Schema(
                                            type="integer",
                                            description=(
                                                "Hour of the day (0–23). "
                                                "Extract directly from the hour row in the table."
                                            )
                                        ),
                                        "temperature_c": Schema(
                                            type="number",
                                            description=(
                                                "Temperature in Celsius. "
                                                "Remove degree symbol. "
                                                "Convert blank/missing to null only if Windy shows no cell."
                                            )
                                        ),
                                        "rain_mm": Schema(
                                            type="number",
                                            description=(
                                                "Rain in millimeters. "
                                                "Empty cell = 0. "
                                                "Never guess values not present in Markdown."
                                            )
                                        ),
                                        "wind_kt": Schema(
                                            type="number",
                                            description=(
                                                "Wind speed in knots as shown in the wind row. "
                                                "Extract the raw integer text inside the colored gradient cell."
                                            )
                                        ),
                                        "wind_gust_kt": Schema(
                                            type="number",
                                            description=(
                                                "Wind gust value from the gust row. "
                                                "If the cell is empty, return 0."
                                            ),
                                            nullable=True
                                        ),
                                        "wind_direction_deg": Schema(
                                            type="number",
                                            description=(
                                                "Numeric direction from rotated arrow CSS transform "
                                                "(e.g. rotate(267deg)). "
                                                "Return the degree number only."
                                            ),
                                            nullable=True
                                        ),
                                        "icon_url": Schema(
                                            type="string",
                                            description=(
                                                "Full URL of the weather icon from the icon row. "
                                                "Use srcset @2x image for highest quality."
                                            ),
                                            nullable=True
                                        )
                                    },
                                    required=[
                                        "time_hour",
                                        "temperature_c",
                                        "rain_mm",
                                        "wind_kt"
                                    ]
                                )
                            )
                        },
                        required=["date", "hours"]
                    )
                )
            },
            required=["location", "metadata", "forecast_days"]
        )

    except Exception as e:
        logger.exception("Failed to build Weather Forecast schema.")
        raise e
    


def build_geolocation_schema() -> Schema:
    """
    Build and return the Geolocation schema, designed to extract location
    coordinates and descriptive details from an image or text input.
    """
    try:
        return Schema(
            type="object",
            properties={
                "latitude": Schema(
                    type="number",
                    description="The determined geographical latitude in decimal degrees. Must be a float."
                ),
                "longitude": Schema(
                    type="number",
                    description="The determined geographical longitude in decimal degrees. Must be a float."
                ),
                "location_name": Schema(
                    type="string",
                    description="The most specific descriptive name for the location (e.g., landmark, building name, or street)."
                ),
                "city": Schema(
                    type="string",
                    description="The city or major locality where the image was taken."
                ),
                "country": Schema(
                    type="string",
                    description="The country where the image was taken."
                ),
                "confidence_score": Schema(
                    type="number",
                    description="A numerical score (0.0 to 1.0) indicating the model's certainty about the extracted location. Use 0.9 or higher for high confidence."
                )
            },
            required=["latitude", "longitude", "city", "country"]
        )
    except Exception as e:
        logger.exception("Failed to build Geolocation schema.")
        raise e


# Exported schemas for direct import across your codebase
WEATHER_FORECAST_SCHEMA = build_weather_schema()
GEOLOCATION_SCHEMA = build_geolocation_schema()