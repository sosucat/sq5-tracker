"""SQ5 Tracker - Web scraping module for apartment pricing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import httpx
from selectolax.parser import HTMLParser


@dataclass
class ApartmentPlan:
    """Represents an apartment floor plan with pricing information."""

    name: str
    price: str | None
    strikethrough_price: str | None
    discount: str | None
    status: str | None

    # CSS selectors for parsing
    _TYPE_SELECTOR: ClassVar[str] = "span.plan-module-scss-module__4ZjhVG__type"
    _PRICE_SELECTOR: ClassVar[str] = "span.plan-module-scss-module__4ZjhVG__price"
    _SPECIAL_SELECTOR: ClassVar[str] = "span.plan-module-scss-module__4ZjhVG__special"
    _STRIKETHROUGH_SELECTOR: ClassVar[str] = "span.plan-module-scss-module__4ZjhVG__strikethrough"
    _SOLD_OUT_SELECTOR: ClassVar[str] = "span.chip-module-scss-module__IVMsSG__root"

    @classmethod
    def from_li_element(cls, li: HTMLParser) -> ApartmentPlan:
        """Create an ApartmentPlan from a list item element."""
        name_elem = li.css_first(cls._TYPE_SELECTOR)
        name = name_elem.text() if name_elem else "Unknown"

        price_elem = li.css_first(cls._PRICE_SELECTOR)
        status_elem = li.css_first(cls._SOLD_OUT_SELECTOR)

        if status_elem and "Sold Out" in status_elem.text():
            return cls(
                name=name,
                price=None,
                strikethrough_price=None,
                discount=None,
                status="Sold Out",
            )

        special_elem = price_elem.css_first(cls._SPECIAL_SELECTOR) if price_elem else None
        strikethrough_elem = price_elem.css_first(cls._STRIKETHROUGH_SELECTOR) if price_elem else None

        # Extract the final price: it's the text node that comes after the strikethrough span
        # The HTML structure is: <price><special>$X</special><strikethrough>$Y</strikethrough>$Z</price>
        # We need to get $Z which is the last text node
        price = None
        if price_elem:
            # Get the full text and remove child span content to isolate the final price
            full_text = price_elem.text()
            # The final price is the last price-like string after removing strikethrough and special text
            strikethrough = strikethrough_elem.text() if strikethrough_elem else None
            special = special_elem.text() if special_elem else None
            
            # Remove known patterns to get the final price
            price = full_text
            if strikethrough:
                price = price.replace(strikethrough, "")
            if special:
                price = price.replace(special, "")
            price = price.strip()

        return cls(
            name=name,
            price=price,
            strikethrough_price=strikethrough_elem.text() if strikethrough_elem else None,
            discount=special_elem.text() if special_elem else None,
            status=None,
        )


class ApartmentScraper:
    """Scraper for apartment floor plan pricing from Square on Fifth website."""

    BASE_URL: ClassVar[str] = "https://www.squareonfifth.com"
    PLAN_URL: ClassVar[str] = "https://www.squareonfifth.com/apartments/three-bedroom/"

    def __init__(self, timeout: float = 10.0) -> None:
        """Initialize the scraper with optional timeout configuration."""
        self.timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Lazy initialization of HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the HTTP client connection."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> ApartmentScraper:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - ensures client is closed."""
        self.close()

    def fetch_page(self, url: str | None = None) -> HTMLParser:
        """Fetch and parse a webpage."""
        target_url = url or self.PLAN_URL
        response = self.client.get(target_url)
        response.raise_for_status()
        return HTMLParser(response.text)

    def extract_plans(self, parser: HTMLParser) -> list[ApartmentPlan]:
        """Extract all apartment plans from the parsed HTML."""
        # Find all list items containing plan information
        li_elements = parser.css("li")
        plans = []

        for li in li_elements:
            # Check if this li contains plan data
            if li.css_first(ApartmentPlan._TYPE_SELECTOR):
                plan = ApartmentPlan.from_li_element(li)
                plans.append(plan)

        return plans

    def get_plan_price(self, plan_name: str, discount: str | None = None) -> str | None:
        """Get the current price for a specific plan, optionally filtered by discount."""
        with self:
            parser = self.fetch_page()
            plans = self.extract_plans(parser)

            for plan in plans:
                if plan.name.lower() == plan_name.lower():
                    if discount is None or discount.lower() in (plan.discount or "").lower():
                        return plan.price

            return None

    def send_price_via_ntfy(self, plan_name: str, price: str | None, topic: str = "sq5_tracker_v0") -> bool:
        """Send the scraped price via ntfy.sh notification."""
        if not price:
            return False

        url = f"https://ntfy.sh/{topic}"
        message = f"C3 Standard price: {price}"

        try:
            self.client.post(url, data=message.encode("utf-8"))
            print(f"Notification sent to {topic}")
            return True
        except Exception as e:
            print(f"Failed to send notification: {e}")
            return False


def main() -> None:
    """Main entry point for the scraper."""
    scraper = ApartmentScraper()

    try:
        parser = scraper.fetch_page()
        plans = scraper.extract_plans(parser)

        print("Three-Bedroom Floor Plans:")
        print("-" * 40)
        for plan in plans:
            if plan.status == "Sold Out":
                print(f"{plan.name}: {plan.status}")
            else:
                price_info = plan.price or "N/A"
                if plan.strikethrough_price:
                    price_info = f"{plan.strikethrough_price} → {price_info}"
                if plan.discount:
                    price_info = f"{price_info} ({plan.discount})"
                print(f"{plan.name}: {price_info}")

        # Get specific C3 Standard price ($50 Off/Mo discount)
        c3_price = scraper.get_plan_price("Standard", discount="$50 Off/Mo")
        print("-" * 40)
        print(f"C3 Standard current price: {c3_price}")

        # Send price via ntfy
        if c3_price:
            scraper.send_price_via_ntfy("C3 Standard", c3_price)

    except httpx.HTTPError as e:
        print(f"HTTP error occurred: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
