import os
import json
import re
import urllib.parse
from typing import Optional
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-3.8-flash')


def extract_json_from_response(text: str) -> dict:
    """Extract JSON from AI response text."""
    try:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(text)
    except Exception as e:
        print(f"JSON parse error: {e}")
        return {}


def add_shopping_links(item: dict, platforms: list):
    """Add shopping search links to a recommendation item."""
    search_terms = item.get("search_terms", "")
    if not search_terms:
        return

    q = urllib.parse.quote_plus(search_terms)

    platform_urls = {
        "amazon": f"https://www.amazon.in/s?k={q}",
        "flipkart": f"https://www.flipkart.com/search?q={q}",
        "ikea": f"https://www.ikea.com/in/en/search/?q={q}",
        "myntra": f"https://www.myntra.com/search?q={q}",
        "meesho": f"https://www.meesho.com/search?q={q}",
        "swiggy": f"https://www.swiggy.com/search?query={q}",
        "zomato": f"https://www.zomato.com/search?q={q}",
        "bookmyshow": f"https://in.bookmyshow.com/search?q={q}",
        "google": f"https://www.google.com/search?q={q}",
        "booking": f"https://www.booking.com/search.html?ss={q}",
        "makemytrip": f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}",
        "bluestone": f"https://www.bluestone.com/search.html?query={q}",
        "tanishq": f"https://www.tanishq.co.in/search?q={q}",
        "caratlane": f"https://www.caratlane.com/search?q={q}",
        "melorra": f"https://www.melorra.com/search?q={q}",
    }

    links = {}
    for p in platforms:
        if p in platform_urls:
            links[p] = platform_urls[p]
    if links:
        item["shopping_links"] = links


# ==================== HOME RECOMMENDATIONS ====================
def get_home_recommendations(budget_input) -> dict:
    prompt = f"""
    I need interior design product recommendations for a home in India with a total budget of Rs {budget_input.total_budget:.2f}.

    Requirements:
    - {budget_input.num_lights} lights
    - {budget_input.num_fans} ceiling fans
    - {budget_input.num_furniture} furniture pieces
    - {budget_input.num_dining_tables} dining tables

    Additional rooms: Living={budget_input.has_living_room}, Kitchen={budget_input.has_kitchen}, Bedroom={budget_input.has_bedroom}
    Additional: {budget_input.additional_requirements or "None"}

    Use Indian brands and INR prices. Return ONLY valid JSON in this exact format:
    {{
      "total_budget": {budget_input.total_budget},
      "budget_breakdown": [
        {{
          "category": "lighting",
          "allocation": 0.0,
          "items": [
            {{"name": "", "description": "", "estimated_price": 0.0, "quantity": 0, "search_terms": ""}}
          ]
        }}
      ],
      "remaining_budget": 0.0,
      "additional_suggestions": []
    }}
    """
    try:
        response = model.generate_content(prompt)
        result = extract_json_from_response(response.text)
        for category in result.get("budget_breakdown", []):
            for item in category.get("items", []):
                add_shopping_links(item, ["amazon", "flipkart", "ikea", "myntra"])
        return result
    except Exception as e:
        return {"error": str(e)}


# ==================== PARTY RECOMMENDATIONS ====================
def get_party_recommendations(budget_input) -> dict:
    prompt = f"""
    Party planning for India with budget Rs {budget_input.total_budget:.2f}.

    Details:
    - Type: {budget_input.party_type}
    - Guests: {budget_input.num_guests}
    - Venue: {budget_input.venue_type or "Not specified"}
    - Catering: {budget_input.needs_catering}
    - Decoration: {budget_input.needs_decoration}
    - Entertainment: {budget_input.needs_entertainment}
    Additional: {budget_input.additional_requirements or "None"}

    Return ONLY valid JSON:
    {{
      "total_budget": {budget_input.total_budget},
      "budget_breakdown": [
        {{
          "category": "venue",
          "allocation": 0.0,
          "items": [
            {{"name": "", "description": "", "estimated_price": 0.0, "quantity": 0, "search_terms": ""}}
          ]
        }}
      ],
      "venue_suggestions": [],
      "remaining_budget": 0.0,
      "additional_suggestions": []
    }}
    """
    try:
        response = model.generate_content(prompt)
        result = extract_json_from_response(response.text)

        category_platforms = {
            "venue": ["google", "booking", "makemytrip"],
            "catering": ["swiggy", "zomato"],
            "food": ["swiggy", "zomato"],
            "decoration": ["amazon", "flipkart", "meesho"],
            "entertainment": ["bookmyshow", "amazon"],
            "gifts": ["amazon", "flipkart", "myntra"],
        }

        for category in result.get("budget_breakdown", []):
            cat_name = category.get("category", "").lower()
            platforms = category_platforms.get(cat_name, ["amazon", "flipkart"])
            for item in category.get("items", []):
                add_shopping_links(item, platforms)
        return result
    except Exception as e:
        return {"error": str(e)}


# ==================== JEWELRY RECOMMENDATIONS ====================
def get_jewelry_recommendations(budget_input, image_path: Optional[str] = None) -> dict:
    base_prompt = f"""
    Jewelry recommendations for India with budget Rs {budget_input.total_budget:.2f}.

    Occasion: {budget_input.occasion}
    Preferences: {budget_input.preferences or "Not specified"}

    Return ONLY valid JSON:
    {{
      "total_budget": {budget_input.total_budget},
      "jewelry_recommendations": [
        {{"item_type": "", "description": "", "style": "", "estimated_price": 0.0, "search_terms": ""}}
      ],
      "remaining_budget": 0.0,
      "styling_tips": []
    }}
    """
    try:
        if image_path and os.path.exists(image_path):
            img = Image.open(image_path)
            prompt = base_prompt + "\nAn outfit image is attached. Suggest matching jewelry considering the colors and style."
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content(base_prompt)

        result = extract_json_from_response(response.text)
        for item in result.get("jewelry_recommendations", []):
            add_shopping_links(
                item,
                ["amazon", "flipkart", "bluestone", "tanishq", "caratlane", "melorra"],
            )
        return result
    except Exception as e:
        return {"error": str(e)}