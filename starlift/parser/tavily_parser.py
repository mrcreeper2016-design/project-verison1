import asyncio
import os
import json
import logging
import re
from datetime import datetime
from dotenv import load_dotenv
import asyncpg
from tavily import AsyncTavilyClient

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

# Initialize Tavily client
tavily_client = AsyncTavilyClient(api_key=TAVILY_API_KEY)

TARGET_SITES = [
    "https://highload.ru/moscow/2025/abstracts",
    "https://highload.ru/spb/2026/abstracts",
    "https://dump-ekb.ru/",
    "https://ontico.ru/"
]

async def init_db_pool():
    """Initialize the asyncpg database connection pool."""
    logger.info("Connecting to the database...")
    try:
        pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            host=DB_HOST,
            port=DB_PORT,
             min_size=1,
             max_size=10
        )
        logger.info("Successfully connected to the database.")
        return pool
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        raise

async def extract_data_with_tavily(site_url: str) -> list[dict]:
    """Use Tavily to extract IT conferences/events data from a given URL."""
    logger.info(f"Extracting IT event data from {site_url} using Tavily API...")

    today = datetime.now().strftime('%Y-%m-%d')
    prompt = (
        f"For events at {site_url}, return ONLY a valid JSON array. "
        f"Keys: event_title, event_date (in Russian, e.g. '10 Мая 2026', or empty string if not specified), event_location (Russian city), event_link, "
        f"event_description (Russian, 3 sentences min), event_status ('future'/'past'), event_schedule (HTML string of <div> elements). "
        f"IMPORTANT: ALL values (other than the title) MUST be Russian! Use double quotes."
    )    

    for attempt in range(2):
        try:
            p = prompt
            if len(p) > 390:
                p = p[:390]
            qna_response = await tavily_client.qna_search(query=p)
            print(f"Raw LLM response (attempt {attempt+1}):")
            print(qna_response)
            
            data = parse_json_response(qna_response)
            if data:
                return data
            else:
                prompt = "ОТВЕТЬ ИСКЛЮЧИТЕЛЬНО И ТОЛЬКО МАССИВОМ JSON, НАЧИНАЯ С [ И ЗАКАНЧИВАЯ ]: " + prompt
        except Exception as e:
            logger.error(f"Error extracting data from {site_url}: {e}")
            break
            
    return []

def parse_json_response(response_text: str) -> list[dict]:
    """Helper to heavily sanitize and parse JSON from an LLM response."""
    try:
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']')
        if start_idx != -1 and end_idx != -1:
            json_str = response_text[start_idx:end_idx+1]
            
            # Fix unquoted keys if any
            json_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
            
            # Additional cleanup of unquoted string values that aren't numbers/booleans?
            # It's safer to just rely on AST / json parse if possible, or demjson.
            # But let's try standard JSON first
            return json.loads(json_str)
        else:
            logger.warning(f"Could not find JSON array in response. Length: {len(response_text)}")
            return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON")
        return []

async def save_event(pool, data: dict):
    """Upsert event data into PostgreSQL (starlift_event)."""
    event_title = data.get("event_title")
    
    if not event_title:
        logger.warning(f"Missing event title. Skipping record: {data}")
        return

    event_date = str(data.get("event_date") or "")
    event_location = str(data.get("event_location") or "")
    event_link = str(data.get("event_link") or "")
    event_description = str(data.get("event_description") or "")
    event_status = str(data.get("event_status") or "future")
    event_schedule = str(data.get("event_schedule") or "")

    event_title = event_title[:200]
    event_status = event_status[:50]
    event_date = event_date[:100]
    event_location = event_location[:200]
    event_link = event_link[:500]

    async with pool.acquire() as connection:
        async with connection.transaction():
            event_record = await connection.fetchrow(
                "SELECT id, date, location, link, description, schedule FROM starlift_event WHERE title = $1",
                event_title
            )

            if event_record:
                event_id = event_record['id']
                logger.info(f"Event '{event_title}' found. Updating.")
                update_fields = {
                    'date': event_date,
                    'location': event_location,
                    'description': event_description,
                    'schedule': event_schedule,
                }
                if not event_record['link'] and event_link:
                    update_fields['link'] = event_link

                if update_fields:
                    set_clauses = ", ".join([f"{k} = ${i+2}" for i, k in enumerate(update_fields.keys())])
                    values = list(update_fields.values())
                    query = f"UPDATE starlift_event SET {set_clauses} WHERE id = $1"
                    await connection.execute(query, event_id, *values)
            else:
                 logger.info(f"Inserting new event: '{event_title}'.")
                 await connection.execute(
                    """
                    INSERT INTO starlift_event (title, status, date, location, link, description, schedule)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    event_title, event_status, event_date, event_location, event_link, event_description, event_schedule
                 )

async def main():
    pool = await init_db_pool()
    if not pool:
        logger.error("Failed to initialize db pool.")
        return

    try:
        for site in TARGET_SITES:
            logger.info(f"Processing site: {site}")
            extracted_data = await extract_data_with_tavily(site)
            
            if not extracted_data:
                 logger.warning(f"No data for {site}")
                 continue
                 
            for item in extracted_data:
                await save_event(pool, item)
    finally:
        await pool.close()
        logger.info("DB closed.")

if __name__ == "__main__":
    asyncio.run(main())