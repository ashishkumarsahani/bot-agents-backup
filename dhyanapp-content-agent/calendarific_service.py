"""
Calendarific API Service for Festival Post Bot.

This service handles:
- Fetching holidays and festivals from Calendarific API
- Filtering for Indian festivals and important days
- Selecting the most important festivals for a given date
"""

import os
import requests
from datetime import datetime, date
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Calendarific API configuration
CALENDARIFIC_API_KEY = os.getenv("CALENDARIFIC_API_KEY", "d7jGco12cIVpPE6KFqRmaEUgse3Xs6UJ")
CALENDARIFIC_BASE_URL = "https://calendarific.com/api/v2/holidays"


class CalendarificService:
    """Service for fetching festivals and holidays from Calendarific API."""

    def __init__(self):
        """Initialize the Calendarific service."""
        self.api_key = CALENDARIFIC_API_KEY

    def get_holidays_for_date(self, target_date: date, country: str = "IN") -> list[dict]:
        """
        Get holidays for a specific date.

        Args:
            target_date: The date to get holidays for
            country: Country code (default: IN for India)

        Returns:
            List of holiday dictionaries
        """
        params = {
            "api_key": self.api_key,
            "country": country,
            "year": target_date.year,
            "month": target_date.month,
            "day": target_date.day
        }

        try:
            print(f"[INFO] Fetching holidays for {target_date} ({country})...")
            response = requests.get(CALENDARIFIC_BASE_URL, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if data.get("meta", {}).get("code") == 200:
                holidays = data.get("response", {}).get("holidays", [])
                print(f"[SUCCESS] Found {len(holidays)} holidays/events")
                return holidays
            else:
                print(f"[WARNING] API returned: {data.get('meta', {})}")
                return []

        except Exception as e:
            print(f"[ERROR] Failed to fetch holidays: {e}")
            return []

    def get_holidays_for_month(self, year: int, month: int, country: str = "IN") -> list[dict]:
        """
        Get all holidays for a specific month.

        Args:
            year: Year
            month: Month (1-12)
            country: Country code

        Returns:
            List of holiday dictionaries
        """
        params = {
            "api_key": self.api_key,
            "country": country,
            "year": year,
            "month": month
        }

        try:
            print(f"[INFO] Fetching holidays for {year}-{month:02d} ({country})...")
            response = requests.get(CALENDARIFIC_BASE_URL, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if data.get("meta", {}).get("code") == 200:
                holidays = data.get("response", {}).get("holidays", [])
                print(f"[SUCCESS] Found {len(holidays)} holidays/events for the month")
                return holidays
            else:
                return []

        except Exception as e:
            print(f"[ERROR] Failed to fetch holidays: {e}")
            return []

    def get_today_holidays(self, country: str = "IN") -> list[dict]:
        """Get holidays for today."""
        return self.get_holidays_for_date(date.today(), country)

    def filter_important_holidays(self, holidays: list[dict], max_count: int = 2) -> list[dict]:
        """
        Filter and rank holidays by importance for India.

        Args:
            holidays: List of holidays from API
            max_count: Maximum number of holidays to return

        Returns:
            List of most important holidays
        """
        if not holidays:
            return []

        # Priority types (higher priority first)
        priority_types = [
            "National holiday",
            "Gazetted Holiday",
            "Public Holiday",
            "Restricted Holiday",
            "Hindu",
            "Muslim",
            "Christian",
            "Sikh",
            "Buddhist",
            "Jain",
            "Observance",
            "Season",
            "Common local holiday",
        ]

        # Important keywords that increase priority
        important_keywords = [
            "diwali", "holi", "dussehra", "navratri", "ganesh", "krishna",
            "ram", "shiva", "durga", "lakshmi", "eid", "christmas", "easter",
            "guru nanak", "buddha", "mahavir", "independence", "republic",
            "gandhi", "ambedkar", "pongal", "onam", "baisakhi", "lohri",
            "makar sankranti", "raksha bandhan", "karva chauth", "chhath"
        ]

        def get_priority(holiday: dict) -> int:
            """Calculate priority score for a holiday."""
            score = 100  # Base score

            # Check type
            holiday_types = holiday.get("type", [])
            for i, ptype in enumerate(priority_types):
                if ptype in holiday_types:
                    score += (len(priority_types) - i) * 10
                    break

            # Check name for important keywords
            name = holiday.get("name", "").lower()
            for keyword in important_keywords:
                if keyword in name:
                    score += 50
                    break

            # Prefer primary holidays
            if holiday.get("primary_type") == "National holiday":
                score += 100

            return score

        # Sort by priority
        sorted_holidays = sorted(holidays, key=get_priority, reverse=True)

        # Return top holidays
        return sorted_holidays[:max_count]

    def get_top_festivals_for_today(self, max_count: int = 2) -> list[dict]:
        """
        Get the top festivals/holidays for today in India.

        Args:
            max_count: Maximum number of festivals to return

        Returns:
            List of top festivals with details
        """
        holidays = self.get_today_holidays("IN")
        return self.filter_important_holidays(holidays, max_count)

    def format_holiday_info(self, holiday: dict) -> dict:
        """
        Format holiday information for post generation.

        Args:
            holiday: Raw holiday data from API

        Returns:
            Formatted holiday info
        """
        return {
            "name": holiday.get("name", "Unknown"),
            "description": holiday.get("description", ""),
            "type": holiday.get("type", []),
            "primary_type": holiday.get("primary_type", ""),
            "date": holiday.get("date", {}).get("iso", ""),
            "country": holiday.get("country", {}).get("name", "India"),
            "locations": holiday.get("locations", "All"),
        }


# Singleton instance
_calendarific_service = None


def get_calendarific_service() -> CalendarificService:
    """Get the singleton instance of the Calendarific service."""
    global _calendarific_service
    if _calendarific_service is None:
        _calendarific_service = CalendarificService()
    return _calendarific_service


if __name__ == "__main__":
    # Quick test
    service = get_calendarific_service()

    print("\n" + "="*60)
    print("Testing Calendarific API")
    print("="*60)

    # Get today's holidays
    today = date.today()
    print(f"\nDate: {today}")

    holidays = service.get_today_holidays()

    if holidays:
        print(f"\nAll holidays today ({len(holidays)}):")
        for h in holidays:
            print(f"  - {h.get('name')} ({h.get('type', [])})")

        top_festivals = service.filter_important_holidays(holidays, 2)
        print(f"\nTop {len(top_festivals)} festivals:")
        for h in top_festivals:
            info = service.format_holiday_info(h)
            print(f"  - {info['name']}")
            print(f"    Type: {info['type']}")
            print(f"    Description: {info['description'][:100]}...")
    else:
        print("\nNo holidays found for today")
