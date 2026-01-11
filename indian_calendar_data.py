"""
Indian Calendar Data - Festivals, Important Days, and National Heroes
This module contains comprehensive data about Indian festivals, religious observances,
and important dates related to national figures.
"""

from datetime import datetime
from typing import Dict, Optional

# Data structure: {month-day: {name, type, description, significance}}
INDIAN_CALENDAR = {
    # January
    "01-01": {
        "name": "New Year's Day",
        "type": "National",
        "description": "Celebration of the new year according to the Gregorian calendar",
        "significance": "A day of new beginnings and resolutions"
    },
    "01-14": {
        "name": "Makar Sankranti / Pongal / Lohri",
        "type": "Hindu/Harvest",
        "description": "Harvest festival marking the transition of the sun into Capricorn",
        "significance": "Celebrated across India with different names - Pongal in Tamil Nadu, Lohri in Punjab, Makar Sankranti in other states"
    },
    "01-15": {
        "name": "Makar Sankranti (Day 2)",
        "type": "Hindu/Harvest",
        "description": "Second day of harvest celebrations",
        "significance": "Mattu Pongal - honoring cattle in Tamil Nadu"
    },
    "01-23": {
        "name": "Netaji Subhas Chandra Bose Jayanti",
        "type": "National Figure",
        "description": "Birth anniversary of freedom fighter Netaji Subhas Chandra Bose",
        "significance": "Remembering the leader who formed the Indian National Army"
    },
    "01-26": {
        "name": "Republic Day",
        "type": "National",
        "description": "Day when the Constitution of India came into effect",
        "significance": "Celebrating India becoming a republic in 1950"
    },

    # February
    "02-13": {
        "name": "Saraswati Puja / Basant Panchami",
        "type": "Hindu",
        "description": "Worship of Goddess Saraswati, deity of knowledge and arts",
        "significance": "Celebrating learning, knowledge, and the arrival of spring"
    },
    "02-19": {
        "name": "Chhatrapati Shivaji Maharaj Jayanti",
        "type": "National Figure",
        "description": "Birth anniversary of Maratha warrior king Shivaji Maharaj",
        "significance": "Honoring the great warrior and administrator"
    },

    # March
    "03-08": {
        "name": "Maha Shivaratri",
        "type": "Hindu",
        "description": "Great night of Lord Shiva",
        "significance": "Devotees observe fast and offer prayers to Lord Shiva"
    },
    "03-25": {
        "name": "Holi",
        "type": "Hindu",
        "description": "Festival of colors",
        "significance": "Celebrating the victory of good over evil and the arrival of spring"
    },

    # April
    "04-06": {
        "name": "Gudi Padwa / Ugadi",
        "type": "Hindu",
        "description": "New Year according to the Hindu lunar calendar",
        "significance": "Celebrated in Maharashtra and parts of South India"
    },
    "04-10": {
        "name": "Mahavir Jayanti",
        "type": "Jain",
        "description": "Birth anniversary of Lord Mahavira, founder of Jainism",
        "significance": "Celebrating the principles of non-violence and truth"
    },
    "04-14": {
        "name": "Ambedkar Jayanti / Baisakhi",
        "type": "National Figure/Sikh",
        "description": "Dr. B.R. Ambedkar's birth anniversary and Sikh New Year",
        "significance": "Honoring the architect of Indian Constitution and harvest festival in Punjab"
    },
    "04-21": {
        "name": "Ram Navami",
        "type": "Hindu",
        "description": "Birth anniversary of Lord Rama",
        "significance": "Celebrating the birth of Lord Rama, hero of Ramayana"
    },

    # May
    "05-01": {
        "name": "May Day / Labour Day",
        "type": "National",
        "description": "International Workers' Day",
        "significance": "Honoring the contributions of workers and laborers"
    },
    "05-23": {
        "name": "Buddha Purnima",
        "type": "Buddhist",
        "description": "Birth anniversary of Gautama Buddha",
        "significance": "Celebrating the birth, enlightenment, and death of Buddha"
    },

    # June
    "06-17": {
        "name": "Eid ul-Adha (Bakrid)",
        "type": "Islamic",
        "description": "Festival of Sacrifice",
        "significance": "Commemorating Prophet Ibrahim's willingness to sacrifice his son (dates vary by lunar calendar)"
    },

    # July
    "07-07": {
        "name": "Rath Yatra",
        "type": "Hindu",
        "description": "Chariot festival of Lord Jagannath",
        "significance": "Famous festival in Puri, Odisha"
    },

    # August
    "08-15": {
        "name": "Independence Day",
        "type": "National",
        "description": "India's independence from British rule",
        "significance": "Celebrating freedom achieved on August 15, 1947"
    },
    "08-19": {
        "name": "Muharram",
        "type": "Islamic",
        "description": "Islamic New Year and mourning period",
        "significance": "Commemorating the martyrdom of Imam Hussain (dates vary by lunar calendar)"
    },
    "08-26": {
        "name": "Janmashtami",
        "type": "Hindu",
        "description": "Birth anniversary of Lord Krishna",
        "significance": "Celebrating the birth of Lord Krishna at midnight"
    },

    # September
    "09-02": {
        "name": "Onam",
        "type": "Hindu/Harvest",
        "description": "Harvest festival of Kerala",
        "significance": "Celebrating King Mahabali's annual visit"
    },
    "09-05": {
        "name": "Teachers' Day",
        "type": "National",
        "description": "Birth anniversary of Dr. Sarvepalli Radhakrishnan",
        "significance": "Honoring teachers and educators"
    },
    "09-07": {
        "name": "Ganesh Chaturthi",
        "type": "Hindu",
        "description": "Birth of Lord Ganesha",
        "significance": "Celebrating the elephant-headed god of wisdom and prosperity"
    },

    # October
    "10-02": {
        "name": "Gandhi Jayanti",
        "type": "National",
        "description": "Birth anniversary of Mahatma Gandhi",
        "significance": "Honoring the Father of the Nation and principles of non-violence"
    },
    "10-12": {
        "name": "Dussehra / Vijayadashami",
        "type": "Hindu",
        "description": "Victory of good over evil",
        "significance": "Celebrating Lord Rama's victory over Ravana"
    },
    "10-24": {
        "name": "Diwali",
        "type": "Hindu",
        "description": "Festival of Lights",
        "significance": "Celebrating the return of Lord Rama to Ayodhya and victory of light over darkness"
    },
    "10-31": {
        "name": "Sardar Patel Jayanti / Rashtriya Ekta Diwas",
        "type": "National Figure",
        "description": "Birth anniversary of Sardar Vallabhbhai Patel",
        "significance": "Honoring the Iron Man of India who unified the country"
    },

    # November
    "11-01": {
        "name": "Karnataka Rajyotsava",
        "type": "State",
        "description": "Formation day of Karnataka state",
        "significance": "Celebrating Karnataka's cultural heritage"
    },
    "11-07": {
        "name": "Chhath Puja",
        "type": "Hindu",
        "description": "Ancient Vedic festival dedicated to Sun God",
        "significance": "Mainly celebrated in Bihar, Jharkhand, and Eastern UP"
    },
    "11-14": {
        "name": "Children's Day",
        "type": "National",
        "description": "Birth anniversary of Jawaharlal Nehru",
        "significance": "Celebrating childhood and honoring India's first Prime Minister"
    },
    "11-15": {
        "name": "Guru Nanak Jayanti",
        "type": "Sikh",
        "description": "Birth anniversary of Guru Nanak Dev Ji",
        "significance": "Celebrating the founder of Sikhism"
    },

    # December
    "12-25": {
        "name": "Christmas",
        "type": "Christian",
        "description": "Birth of Jesus Christ",
        "significance": "Celebrating the birth of Jesus Christ"
    },
}

# Additional important figures and their birth/death anniversaries
IMPORTANT_FIGURES = {
    "01-12": "Swami Vivekananda's birth anniversary - National Youth Day",
    "02-28": "C.V. Raman's birth anniversary - National Science Day (discovery of Raman Effect)",
    "03-23": "Bhagat Singh's martyrdom day",
    "04-13": "Jallianwala Bagh Massacre remembrance",
    "05-07": "Rabindranath Tagore's birth anniversary",
    "05-27": "Jawaharlal Nehru's death anniversary",
    "06-03": "Maharana Pratap's birth anniversary",
    "07-27": "APJ Abdul Kalam's birth anniversary",
    "08-09": "Quit India Movement day",
    "11-11": "Maulana Abul Kalam Azad's birth anniversary - National Education Day",
    "11-19": "Rani Lakshmibai's birth anniversary",
    "12-06": "Dr. B.R. Ambedkar's death anniversary - Mahaparinirvan Diwas",
    "12-23": "Kisan Diwas - Chaudhary Charan Singh's birth anniversary",
}

def get_event_for_date(date: datetime) -> Optional[Dict]:
    """Get event information for a specific date"""
    date_key = date.strftime("%m-%d")

    if date_key in INDIAN_CALENDAR:
        return INDIAN_CALENDAR[date_key]

    if date_key in IMPORTANT_FIGURES:
        return {
            "name": IMPORTANT_FIGURES[date_key],
            "type": "National Figure",
            "description": IMPORTANT_FIGURES[date_key],
            "significance": "Remembering and honoring their contributions to India"
        }

    return None

def get_all_events() -> Dict:
    """Get all events in the calendar"""
    all_events = {}
    all_events.update(INDIAN_CALENDAR)

    for date_key, description in IMPORTANT_FIGURES.items():
        if date_key not in all_events:
            all_events[date_key] = {
                "name": description,
                "type": "National Figure",
                "description": description,
                "significance": "Remembering and honoring their contributions to India"
            }

    return all_events
