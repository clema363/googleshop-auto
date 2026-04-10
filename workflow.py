import asyncio
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ─── Config ────────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = "z-ai/glm-5.1"
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
FIBERY_TOKEN = os.getenv("FIBERY_TOKEN")
FIBERY_URL = os.getenv("FIBERY_URL")

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


# ─── Helpers ───────────────────────────────────────────────────────────────────
def extract_emails_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    emails = EMAIL_REGEX.findall(text)
    blacklist = ["example.com", "sentry.io", "w3.org", "schema.org", "your-email"]
    return [e for e in set(emails) if not any(b in e for b in blacklist)]


def extract_footer_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    footer_tags = soup.find_all(["footer"]) + soup.find_all(
        attrs={"class": re.compile(r"footer|Footer|FOOTER", re.I)}
    )
    for tag in footer_tags:
        for a in tag.find_all("a", href=True):
            full_url = urljoin(base_url, a["href"])
            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                links.append(full_url)
    return list(set(links))


def extract_page_text(html: str, max_chars: int = 3000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:max_chars]


async def get_merchant_description(
    page_text: str, client: httpx.AsyncClient
) -> str | None:
    if not OPENROUTER_API_KEY:
        return None
    try:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Voici le texte extrait du site web d'un commerçant :\n\n"
                            f"{page_text}\n\n"
                            "En une ou deux phrases, décris l'activité principale de ce commerçant "
                            "(ce qu'il vend ou le service qu'il propose). Réponds uniquement avec la description, sans introduction."
                        ),
                    }
                ],
            },
            timeout=20,
        )
        data = response.json()
        if "choices" not in data:
            print(f"  [OpenRouter] réponse inattendue: {data}")
            return None
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [OpenRouter] erreur: {e}")
        return None


async def search_places(query: str, client: httpx.AsyncClient) -> list[dict]:
    resp = await client.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY or "",
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.id",
        },
        json={"textQuery": query, "pageSize": 1},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"Erreur Google Places {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    places = resp.json().get("places", [])
    return [p for p in places if p.get("websiteUri")]


async def scrape_shop(website_uri: str, client: httpx.AsyncClient) -> dict:
    base_url = website_uri.rstrip("/")
    try:
        resp = await client.get(base_url, timeout=15, follow_redirects=True)
        homepage_html = resp.text
        print(f"  [scrape] page chargée ({len(homepage_html)} chars)")
    except Exception as e:
        print(f"  [scrape] échec chargement: {e}")
        return {"email": None, "description": None}

    page_text = extract_page_text(homepage_html)
    print(f"  [scrape] texte extrait ({len(page_text)} chars), appel OpenRouter...")
    description = await get_merchant_description(page_text, client)
    print(f"  [scrape] description: {description}")

    emails = extract_emails_from_html(homepage_html)
    if emails:
        return {"email": emails[0], "description": description}

    for link in extract_footer_links(homepage_html, base_url)[:10]:
        try:
            page_resp = await client.get(link, timeout=15, follow_redirects=True)
            emails = extract_emails_from_html(page_resp.text)
            if emails:
                return {"email": emails[0], "description": description}
        except Exception:
            continue

    return {"email": None, "description": description}


async def fibery_account_exists(website: str, client: httpx.AsyncClient) -> bool:
    payload = [
        {
            "command": "fibery.entity/query",
            "args": {
                "query": {
                    "q/from": "Sales CRM/Account",
                    "q/select": ["fibery/id"],
                    "q/where": ["=", ["Sales CRM/Website"], "$website"],
                    "q/limit": 1,
                },
                "params": {"$website": website},
            },
        }
    ]
    resp = await client.post(
        FIBERY_URL or "",
        headers={
            "Authorization": f"Token {FIBERY_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return len(resp.json()[0].get("result", [])) > 0


async def fibery_create_account(shop: dict, client: httpx.AsyncClient) -> None:
    payload = [
        {
            "command": "fibery.entity/create",
            "args": {
                "type": "Sales CRM/Account",
                "entity": {
                    "Sales CRM/Name": shop.get("name", ""),
                    "Sales CRM/Website": shop.get("website", ""),
                    "Sales CRM/Email": shop.get("email") or "",
                    "Sales CRM/Phone": shop.get("phone") or "",
                    "Sales CRM/Description": shop.get("description") or "",
                },
            },
        }
    ]
    resp = await client.post(
        FIBERY_URL or "",
        headers={
            "Authorization": f"Token {FIBERY_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()


# ─── Workflow principal ─────────────────────────────────────────────────────────
async def run_workflow_result(query: str) -> list[dict]:
    results = []

    async with httpx.AsyncClient(headers=HEADERS) as client:
        print(f"Recherche : {query}")
        places = await search_places(query, client)
        print(f"{len(places)} commerces avec site web trouvés\n")

        for i, place in enumerate(places, 1):
            name = place.get("displayName", {}).get("text", "")
            website = place.get("websiteUri", "").rstrip("/")
            phone = place.get("nationalPhoneNumber", "")
            address = place.get("formattedAddress", "")

            print(f"[{i}/{len(places)}] {name} — {website}")

            scraped = await scrape_shop(website, client)
            email = scraped["email"]
            description = scraped["description"]

            shop = {
                "name": name,
                "website": website,
                "phone": phone,
                "address": address,
                "email": email,
                "description": description,
            }

            exists = await fibery_account_exists(website, client)
            if exists:
                status = "already_exists"
            elif not email:
                status = "no_email"
            else:
                await fibery_create_account(shop, client)
                status = "created"

            print(f"  email: {email or '—'}  |  status: {status}")
            results.append({**shop, "status": status})

    print(f"\n─── Résumé ───")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return results


async def run_workflow(query: str) -> None:
    await run_workflow_result(query)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python workflow.py "Magasin vélo Rennes"')
        sys.exit(1)
    asyncio.run(run_workflow(sys.argv[1]))
